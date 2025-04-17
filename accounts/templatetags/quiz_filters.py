# quiz_filters.py
from django import template

register = template.Library()

@register.filter
def map(iterable, attribute):
    """
    Extracts the specified attribute from each object in the iterable and returns a list.
    Example: {{ quizzes|map:"id" }} returns [1, 2, 3, ...] for quiz IDs.
    """
    return [getattr(item, attribute) for item in iterable]

@register.filter
def get_item(dictionary, key):
    """
    Retrieves the value for the given key from a dictionary.
    Used in the template to get quiz selected answers.
    """
    return dictionary.get(key)