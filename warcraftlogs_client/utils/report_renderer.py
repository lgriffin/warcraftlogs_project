from jinja2 import Environment, FileSystemLoader
import os

def render_markdown_template(template_name: str, context: dict, template_dir: str = "templates") -> str:
    """
    Renders a Jinja2 Markdown template with the given context.

    Args:
        template_name: Filename of the template (e.g., healing_report.md.j2)
        context: Dictionary containing values for template variables
        template_dir: Folder where template lives (default: 'templates')

    Returns:
        Rendered Markdown as string
    """
    env = Environment(
        loader=FileSystemLoader(template_dir),
        trim_blocks=True,
        lstrip_blocks=True
    )
    template = env.get_template(template_name)
    return template.render(context)
