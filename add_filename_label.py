#!/usr/bin/env python3
"""
指定フォルダ内の画像/PDFに、元ファイル名を黒文字で追記します。

使い方:
    python3 add_filename_label.py /path/to/folder
"""

import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat
from pdf2image import convert_from_path


TARGET_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
FILENAME_PATTERN = re.compile(r"^(現|A)-\d+$")

BASIC_FONT_SIZE = 20
SMALL_FONT_SIZE = 18
PREFERRED_BRIGHTNESS = 220
ACCEPTABLE_BRIGHTNESS = 200
DARK_PIXEL_THRESHOLD = 110
PREFERRED_DARK_RATIO = 0.03
ACCEPTABLE_DARK_RATIO = 0.08
SEARCH_MARGIN = 12
TEXT_PADDING = 4


def find_font_path() -> str:
    """
    Mac標準の日本語フォントを探します。
    見つからない場合は文字化けを避けるため、エラーにします。
    """
    font_candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
    ]

    for font_path in font_candidates:
        if Path(font_path).exists():
            return font_path

    raise FileNotFoundError(
        "日本語フォントが見つかりませんでした。"
        " /System/Library/Fonts/ヒラギノ角ゴシック W3.ttc を確認してください。"
    )


def load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    """指定サイズのフォントを読み込みます。"""
    return ImageFont.truetype(font_path, size)


def get_text_size(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    """描画する文字の横幅と高さを取得します。"""
    dummy_image = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy_image)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def average_brightness(gray_image: Image.Image, box: tuple[int, int, int, int]) -> float:
    """指定範囲の平均明るさを返します。255に近いほど白いです。"""
    region = gray_image.crop(box)
    return float(ImageStat.Stat(region).mean[0])


def build_positions(length: int, window: int, margin: int, from_right: bool) -> list[int]:
    """
    探索候補の座標を作ります。
    x方向は右から左、y方向は上から下に調べます。
    """
    if length <= window:
        return [0]

    step = max(4, min(16, window // 3))
    start = margin
    end = max(margin, length - window - margin)

    if from_right:
        positions = list(range(end, start - 1, -step))
        if positions[-1] != start:
            positions.append(start)
    else:
        positions = list(range(start, end + 1, step))
        if positions[-1] != end:
            positions.append(end)

    return positions


def dark_pixel_ratio(gray_image: Image.Image, box: tuple[int, int, int, int]) -> float:
    """
    指定範囲に黒い文字・濃い線がどれくらい含まれるかを調べます。
    0に近いほど、既存文字などと重なりにくい場所です。
    """
    region = gray_image.crop(box)
    histogram = region.histogram()
    dark_pixels = sum(histogram[:DARK_PIXEL_THRESHOLD])
    total_pixels = region.size[0] * region.size[1]
    if total_pixels == 0:
        return 1.0
    return dark_pixels / total_pixels


def find_label_area(
    image: Image.Image,
    text_width: int,
    text_height: int,
) -> tuple[int, int] | None:
    """
    右上付近から、文字が収まりそうな明るい/余白っぽい領域を探します。

    探索順:
    1. 右上から開始
    2. 下方向へ少しずつ移動
    3. 見つからなければ左方向へ移動して、また下方向へ探索

    完全な白である必要はありません。
    既存文字や濃い線が少ない場所なら、多少背景が白でなくても候補にします。
    """
    width, height = image.size
    box_width = text_width + TEXT_PADDING * 2
    box_height = text_height + TEXT_PADDING * 2

    if box_width > width or box_height > height:
        return None

    gray_image = image.convert("L")
    x_positions = build_positions(width, box_width, SEARCH_MARGIN, from_right=True)
    y_positions = build_positions(height, box_height, SEARCH_MARGIN, from_right=False)

    for x in x_positions:
        for y in y_positions:
            box = (x, y, x + box_width, y + box_height)
            brightness = average_brightness(gray_image, box)
            dark_ratio = dark_pixel_ratio(gray_image, box)

            if (
                brightness >= PREFERRED_BRIGHTNESS
                and dark_ratio <= ACCEPTABLE_DARK_RATIO
            ):
                return (x + TEXT_PADDING, y + TEXT_PADDING)

            if (
                brightness >= ACCEPTABLE_BRIGHTNESS
                and dark_ratio <= PREFERRED_DARK_RATIO
            ):
                return (x + TEXT_PADDING, y + TEXT_PADDING)

    return None


def find_best_fallback_area(
    image: Image.Image,
    text_width: int,
    text_height: int,
) -> tuple[int, int]:
    """
    理想的な場所が見つからない場合の最終候補を探します。
    既存文字や濃い要素との重なりが少なく、比較的明るく、右上に近い場所を選びます。
    """
    width, height = image.size
    box_width = min(text_width + TEXT_PADDING * 2, width)
    box_height = min(text_height + TEXT_PADDING * 2, height)

    gray_image = image.convert("L")
    x_positions = build_positions(width, box_width, SEARCH_MARGIN, from_right=True)
    y_positions = build_positions(height, box_height, SEARCH_MARGIN, from_right=False)

    best_position = (0, 0)
    best_score = -1_000_000.0

    for x in x_positions:
        for y in y_positions:
            box = (x, y, x + box_width, y + box_height)
            brightness = average_brightness(gray_image, box)
            dark_ratio = dark_pixel_ratio(gray_image, box)

            # 右上に近いほど少し加点します。ただし最優先は濃い要素との重なり回避です。
            right_distance = (width - box_width) - x
            top_distance = y
            position_penalty = (right_distance + top_distance) * 0.01
            score = brightness - (dark_ratio * 900) - position_penalty

            if score > best_score:
                best_score = score
                best_position = (x, y)

    return (best_position[0] + TEXT_PADDING, best_position[1] + TEXT_PADDING)


def choose_text_position(
    image: Image.Image,
    text: str,
    font_path: str,
) -> tuple[tuple[int, int], ImageFont.FreeTypeFont]:
    """
    基本は18pxで配置します。
    文字が画像内に収まらない場合だけ10pxに縮小します。
    """
    font = load_font(font_path, BASIC_FONT_SIZE)
    text_width, text_height = get_text_size(text, font)
    box_width = text_width + TEXT_PADDING * 2
    box_height = text_height + TEXT_PADDING * 2

    if box_width > image.width or box_height > image.height:
        font = load_font(font_path, SMALL_FONT_SIZE)
        text_width, text_height = get_text_size(text, font)

    position = find_label_area(image, text_width, text_height)
    if position is None:
        position = find_best_fallback_area(image, text_width, text_height)
    return position, font


def load_image_file(file_path: Path) -> Image.Image:
    """jpg/jpeg/pngを読み込み、向き情報を反映してRGB画像にします。"""
    with Image.open(file_path) as image:
        image = ImageOps.exif_transpose(image)
        return image.convert("RGB")


def load_pdf_first_page(file_path: Path) -> Image.Image:
    """PDFの1ページ目だけを画像に変換します。"""
    try:
        pages = convert_from_path(
            str(file_path),
            dpi=200,
            first_page=1,
            last_page=1,
        )
    except Exception as error:
        raise RuntimeError(
            "PDFの画像変換に失敗しました。popplerが未インストールの可能性があります。"
        ) from error

    if not pages:
        raise RuntimeError("PDFの1ページ目を読み込めませんでした。")

    return pages[0].convert("RGB")


def load_source_as_image(file_path: Path) -> Image.Image:
    """対象ファイルを画像として読み込みます。"""
    if file_path.suffix.lower() == ".pdf":
        return load_pdf_first_page(file_path)
    return load_image_file(file_path)


def collect_target_files(folder_path: Path) -> list[Path]:
    """対象拡張子かつファイル名ルールに合うファイルだけを集めます。"""
    files = []
    for file_path in folder_path.iterdir():
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in TARGET_EXTENSIONS:
            continue
        if not FILENAME_PATTERN.match(file_path.stem):
            continue
        files.append(file_path)

    return sorted(files, key=lambda path: path.name)


def make_output_path(output_folder: Path, source_file: Path) -> Path:
    """PDFはpng、それ以外は元の拡張子のまま保存先を作ります。"""
    if source_file.suffix.lower() == ".pdf":
        return output_folder / f"{source_file.stem}.png"
    return output_folder / source_file.name


def draw_filename(image: Image.Image, text: str, font_path: str) -> Image.Image:
    """画像にファイル名を黒文字で描画します。"""
    output_image = image.copy()
    draw = ImageDraw.Draw(output_image)
    position, font = choose_text_position(output_image, text, font_path)
    draw.text(position, text, fill=(0, 0, 0), font=font)
    return output_image


def process_folder(folder_path: Path) -> int:
    """フォルダ内の対象ファイルを処理し、成功件数を返します。"""
    if not folder_path.exists():
        raise FileNotFoundError(f"フォルダが存在しません: {folder_path}")
    if not folder_path.is_dir():
        raise NotADirectoryError(f"フォルダではありません: {folder_path}")

    target_files = collect_target_files(folder_path)
    if not target_files:
        raise FileNotFoundError(
            "対象ファイルが見つかりません。"
            " ファイル名は「現-XXX」または「A-XXX」、拡張子は jpg/jpeg/png/pdf にしてください。"
        )

    font_path = find_font_path()
    output_folder = folder_path / "output"
    output_folder.mkdir(exist_ok=True)

    success_count = 0
    error_count = 0

    for file_path in target_files:
        try:
            image = load_source_as_image(file_path)
            labeled_image = draw_filename(image, file_path.stem, font_path)
            output_path = make_output_path(output_folder, file_path)
            labeled_image.save(output_path)
            success_count += 1
            print(f"OK: {file_path.name} -> output/{output_path.name}")
        except Exception as error:
            error_count += 1
            print(f"ERROR: {file_path.name}: {error}", file=sys.stderr)

    print("----")
    print(f"処理成功: {success_count}件")
    print(f"処理失敗: {error_count}件")

    return success_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="画像/PDFの白い領域に元ファイル名を描画します。"
    )
    parser.add_argument("folder", help="処理したいフォルダのパス")
    args = parser.parse_args()

    try:
        process_folder(Path(args.folder).expanduser())
    except Exception as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
