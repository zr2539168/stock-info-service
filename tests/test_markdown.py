from app.markdown import render_markdown


def test_render_markdown_outputs_html() -> None:
    html = str(render_markdown("## 标题\n\n- 项目\n\n[来源](https://example.com)"))

    assert "<h2>" in html
    assert "<li>" in html
    assert 'href="https://example.com"' in html
