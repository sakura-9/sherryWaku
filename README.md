# sherryWaku
## 必要ライブラリ
```python3 -m pip install Pillow pdf2image```

PDFを画像化するために、Macでは poppler も必要です。

```brew install poppler```

Homebrew が入っていない場合は、先にこちらを入れます。

```/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"```

## 実行手順
対象ファイルが入ったフォルダを指定して実行します。

```cd /Users/sakura/Documents/Codex/2026-05-05/https-github-com-sakura-9-sherrywaku```

```python3 add_filename_label.py /path/to/folder```

## 例：
```python3 add_filename_label.py /Users/sakura/Downloads```
