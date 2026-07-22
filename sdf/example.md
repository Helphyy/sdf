# SDF example

A quick tour of what the live preview renders. Edit the left pane and watch the
right pane update.

## Text

Regular text, **bold**, *italic*, ***bold italic***, `inline code`,
~~strikethrough~~, and a [link](https://github.com/Textualize/textual).

> A blockquote.
> It can span multiple lines.

## Lists

- Unordered item
- Another item
  - Nested item
  - Nested item
- Back to top level

1. First
2. Second
3. Third

Task list:

- [x] Reload the buffer on an external change
- [x] Persist settings under ~/.config/sdf/
- [ ] Read this example

## Code

```python
def watch(path):
    """Reload when the file changes on disk."""
    while True:
        if changed(path):
            reload(path)
```

## Table

| Key      | Action                  |
|----------|-------------------------|
| Ctrl+S   | Save                    |
| Ctrl+F   | Cycle view              |
| Ctrl+W   | Cycle width ratio       |
| Ctrl+T   | Toggle transparency     |

## Quote and rule

Horizontal rule below:

---

That is it. Press Ctrl+Q to quit.
