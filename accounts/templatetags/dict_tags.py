from django import template

register = template.Library()

@register.filter
def setitem(dictionary, key):
    """
    A filter to allow setting a key in a dictionary in a Django template.
    Returns the dictionary so it can be chained.
    """
    return dictionary

@register.filter
def setvalue(dictionary, value):
    """
    A filter to set a value in a dictionary in a Django template.
    This is a placeholder filter to complete the chain.
    """
    return value