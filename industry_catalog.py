"""Descriptive activities; these labels do not create new scorecard weights."""
ACTIVITIES = [
    'Event planning and music events', 'Entertainment and live performances',
    'Plastic recycling and manufacturing', 'Manufacturing',
    'Wholesale / distribution', 'Construction / trades', 'Retail',
    'Restaurant / hospitality', 'Professional services', 'Transportation',
    'Recycling / waste management', 'Digital publishing',
    'E-commerce', 'Personal care and beauty services', 'Health care',
    'Agriculture', 'Real estate and property management', 'Education and training',
    'Automotive sales and services', 'Technology and software',
]


def options(scoring, current=None, blank=False):
    return list(dict.fromkeys(([''] if blank else []) + list(scoring) + ACTIVITIES + ([current] if current else [])))
