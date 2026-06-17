import mwparserfromhell
import hashlib
import sys

try:
    # mwparserfromhell >= 0.6
    from mwparserfromhell.nodes.extras.attribute import Attribute
except Exception:  # pragma: no cover
    # Fallback for older mwparserfromhell layouts
    Attribute = None

def get_sha1(*args) -> str:
    sha1 = hashlib.sha1()
    for arg in args:
        sha1.update(str(arg).encode('utf-8'))
    return sha1.hexdigest()

def normalize_ref_tag(tag):
    # Remove any leading or trailing newlines from the contents of the tag
    stripped_content = tag.contents.strip()
    # Create a new tag with the stripped content
    new_tag = mwparserfromhell.nodes.Tag(tag.tag, stripped_content)
    # Preserve all attributes, but enforce double quotes around the value of name= on <ref>
    for attribute in tag.attributes:
        try:
            attr_name = str(attribute.name)
        except Exception:
            attr_name = attribute.name
        if attr_name == "name":
            # Recreate the attribute with explicit double quotes
            # mwparserfromhell Attribute signature: Attribute(name, value=None, quotes=None)
            if Attribute is None:
                raise RuntimeError(
                    "mwparserfromhell Attribute class could not be imported; "
                    "please upgrade mwparserfromhell"
                )
            new_attr = Attribute(attribute.name, attribute.value, '"')
            new_tag.attributes.append(new_attr)
        else:
            new_tag.attributes.append(attribute)
    # Preserve the self-closing and padding properties
    new_tag.self_closing = tag.self_closing
    if tag.self_closing:
        new_tag.padding = ' '
    return new_tag

def normalize_template(template):
    template_name = template.name.strip().replace("_", " ")
    if template.name.isupper():
        template.name = template_name
    else:
        template.name = template_name.capitalize()
    params = template.params
    named_params = sorted([p for p in params if "=" in str(p)])
    unnamed_params = [p for p in params if "=" not in str(p)]

    new_template = mwparserfromhell.nodes.Template(template.name)

    for param in unnamed_params + named_params:
        key = str(param.name).strip().replace("_", " ")
        value = str(param.value).strip()
        value = ' '.join(value.split())
        value = '\n'.join([line.strip() for line in value.splitlines() if line.strip()])

        # Recurse into nested templates and links
        parsed_value = mwparserfromhell.parse(value)
        for node in parsed_value.nodes:
            if isinstance(node, mwparserfromhell.nodes.Template):
                value = str(normalize_template(node))
            if isinstance(node, mwparserfromhell.nodes.Wikilink):
                node = normalize_node(node)
                parsed_value.replace(node, node)
        value = str(parsed_value)

        new_template.add(key, value, showkey=param.showkey)

    return new_template

def normalize_node(node):
    if isinstance(node, mwparserfromhell.nodes.Template):
        return normalize_template(node)

    elif isinstance(node, mwparserfromhell.nodes.ExternalLink):
        parsed_title = mwparserfromhell.parse(str(node.title))
        for nested_node in parsed_title.nodes:
            normalized_node = normalize_node(nested_node)
            parsed_title.replace(nested_node, normalized_node)
        node.title = str(parsed_title)

    elif isinstance(node, mwparserfromhell.nodes.Tag):
        if node.tag == 'ref':
            node = normalize_ref_tag(node)
            if node.contents:  # If the tag has contents, parse and normalize them
                parsed_contents = mwparserfromhell.parse(node.contents)
                for nested_node in parsed_contents.nodes:
                    normalized_node = normalize_node(nested_node)
                    parsed_contents.replace(nested_node, normalized_node)
                node.contents = str(parsed_contents)
        else:
            parsed_contents = mwparserfromhell.parse(node.contents)
            for nested_node in parsed_contents.nodes:
                normalized_node = normalize_node(nested_node)
                parsed_contents.replace(nested_node, normalized_node)
            node.contents = str(parsed_contents)

    elif isinstance(node, mwparserfromhell.nodes.Wikilink):
        node.title = str(node.title).replace("_", " ")

    return node

def normalize_wikitext(wikitext: str) -> str:
    # Pre-process list items
    lines = wikitext.splitlines()
    for i, line in enumerate(lines):
        # Identify leading list markers
        leading_markers = ''
        j = 0
        while j < len(line) and line[j] in (':', '*', '#'):
            leading_markers += line[j]
            j += 1
        # Only add a space if there's content immediately following the markers
        if leading_markers and j < len(line) and line[j] != ' ':
            lines[i] = leading_markers + ' ' + line[j:]
    adjusted_wikitext = "\n".join(lines)

    # Proceed with normalization
    wikicode = mwparserfromhell.parse(adjusted_wikitext)
    for node in wikicode.nodes:
        normalized_node = normalize_node(node)
        wikicode.replace(node, normalized_node)
    return str(wikicode).strip()


if __name__ == '__main__':
    # Simple CLI utility: normalize a single wikitext argument
    if len(sys.argv) > 1:
        print(normalize_wikitext(sys.argv[1]))
