"""Word search shared by order history and review lists.

«usb хаб | hub» -> [["usb", "хаб"], ["hub"]]: a text matches if it has every word of any one
alternative.  No query matches everything.
"""


def alts(query):
    found = [[w for w in q.lower().split() if w] for q in (query or "").split("|")]
    return [a for a in found if a] or [[]]


def match(text, alternatives):
    text = text.lower()
    return any(all(w in text for w in words) for words in alternatives)


if __name__ == "__main__":
    assert alts("USB хаб | hub") == [["usb", "хаб"], ["hub"]]
    assert alts(None) == alts(" | ") == [[]]
    assert match("Любой текст", alts(None))
    assert match("Хороший USB-хаб", alts("usb хаб | hub")) and match("hub ok", alts("usb хаб | hub"))
    assert not match("только usb", alts("usb хаб"))
    print("ok")
