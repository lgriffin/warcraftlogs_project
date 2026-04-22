from jinja2 import Environment, FileSystemLoader

from .. import paths


def render_markdown_template(template_name: str, context: dict, template_dir: str | None = None) -> str:
    """
    Renders a Jinja2 Markdown template with the given context.

    Args:
        template_name: Filename of the template (e.g., healing_report.md.j2)
        context: Dictionary containing values for template variables
        template_dir: Folder where template lives

    Returns:
        Rendered Markdown as string
    """
    template_dir = template_dir or str(paths.get_template_dir())
    env = Environment(
        loader=FileSystemLoader(template_dir),
        trim_blocks=True,
        lstrip_blocks=True
    )
    template = env.get_template(template_name)
    return template.render(context)
