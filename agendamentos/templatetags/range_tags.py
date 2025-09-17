from django import template
register = template.Library()

@register.filter
def until(value, end):
    """Gera range(value, end)"""
    return range(value, end)
