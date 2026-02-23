
import markdown
from weasyprint import HTML, CSS

# 1. Read the Markdown file
with open("/home/abiorh/hackathon/agentic_commerce/omniclaw/docs/STRATEGIC_ROADMAP.md", "r") as f:
    text = f.read()

# 2. Convert to HTML
html_content = markdown.markdown(text, extensions=['tables', 'fenced_code'])

# 3. Add Professional Styling
css_style = """
    @page {
        size: A4;
        margin: 2cm;
        @bottom-right {
            content: counter(page);
            font-family: 'Helvetica', sans-serif;
            font-size: 10pt;
        }
    }
    body {
        font-family: 'Helvetica', 'Arial', sans-serif;
        line-height: 1.6;
        color: #333;
        font-size: 11pt;
    }
    h1 {
        color: #2c3e50;
        border-bottom: 2px solid #2c3e50;
        padding-bottom: 10px;
        margin-top: 40px;
    }
    h2 {
        color: #e67e22; /* Use a brand color for H2 */
        margin-top: 30px;
        border-bottom: 1px solid #eee;
        padding-bottom: 5px;
    }
    h3 {
        color: #34495e;
        margin-top: 25px;
    }
    blockquote {
        background: #f9f9f9;
        border-left: 5px solid #ccc;
        margin: 1.5em 10px;
        padding: 0.5em 10px;
        font-style: italic;
        color: #555;
    }
    code {
        background-color: #f4f4f4;
        padding: 2px 5px;
        border-radius: 3px;
        font-family: 'Courier New', monospace;
        font-size: 0.9em;
    }
    pre {
        background-color: #f4f4f4;
        padding: 15px;
        border-radius: 5px;
        white-space: pre-wrap;
        word-wrap: break-word;
        font-family: 'Courier New', monospace;
        font-size: 0.9em;
        border: 1px solid #ddd;
    }
    /* Tables */
    table {
        border-collapse: collapse;
        width: 100%;
        margin-bottom: 20px;
    }
    th, td {
        border: 1px solid #ddd;
        padding: 8px;
        text-align: left;
    }
    th {
        background-color: #f2f2f2;
        color: #333;
    }
    tr:nth-child(even) {background-color: #f9f9f9;}
    
    /* Cover Page Emulation for Title */
    h1:first-of-type {
        text-align: center;
        font-size: 28pt;
        border: none;
        margin-top: 100px;
        margin-bottom: 50px;
    }
"""

html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>OmniClaw Strategic Roadmap</title>
</head>
<body>
    {html_content}
</body>
</html>
"""

# 4. Generate PDF
output_path = "/home/abiorh/hackathon/agentic_commerce/omniclaw/docs/OmniClaw_Strategic_Roadmap_2026.pdf"
HTML(string=html_template).write_pdf(output_path, stylesheets=[CSS(string=css_style)])

print(f"PDF generated successfully at: {output_path}")
