css = """
/* Light Mode Variables */
:root[data-theme="light"] {
    --bg-dark: #f0f2f5;
    --panel-bg: #ffffff;
    --border-color: #d1d5da;
    --text-main: #24292e;
    --text-dim: #586069;
}
"""
with open('style.css', 'a') as f:
    f.write(css)
