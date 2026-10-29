"""A product's id from what the user gives: a bare id or a link to the product.  Each store passes its own patterns."""
import re

NUMBER = r"^\s*(\d+)\s*\Z"          # a bare id, spaces around it allowed


def first_group(id_or_url, error, *patterns):
    """Group 1 of the first pattern found in id_or_url, else ValueError(error) naming what the store wants."""
    s = str(id_or_url)
    m = next(filter(None, (re.search(p, s) for p in patterns)), None)
    if not m:
        raise ValueError(error)
    return m.group(1)
