from app.markdown import render_markdown


def test_render_markdown_outputs_html() -> None:
    html = str(render_markdown("## 标题\n\n- 项目\n\n[来源](https://example.com)"))

    assert "<h2>" in html
    assert "<li>" in html
    assert 'href="https://example.com"' in html


def test_render_markdown_outputs_tables() -> None:
    html = str(render_markdown("| 指标 | 最新价 |\n|---|---:|\n| AAPL | 200 |"))

    assert "<table>" in html
    assert "<th>指标</th>" in html
    assert "<td>AAPL</td>" in html
