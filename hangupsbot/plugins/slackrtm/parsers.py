# -*- coding: utf-8 -*-
# pylint: skip-file

import re
import uuid

from reparser import (
    Parser,
    Token,
    MatchGroup,
)

from sync.parser import (
    get_formatted,
)


SLACK_STYLE = {
    (0, 0, 0): '{text}',
    (1, 0, 0): '*{text}*',
    (0, 1, 0): '_{text}_',
    (1, 1, 0): '_*{text}*_',
    (0, 0, 1): '<{url}|{text}>',
    (1, 0, 1): '*<{url}|{text}>*',
    (0, 1, 1): '_<{url}|{text}>_',
    (1, 1, 1): '_*<{url}|{text}>*_',
    'line_break': '\n',
    'ignore_links_matching_text': True,
    'allow_hidden_url': True,
    'escape_html': False,
    'escape_markdown': False,
}


# slack to hangups

def markdown1(tag):
    """Return sequence of start and end regex patterns for simple Markdown tag"""
    return (markdown1_start.format(tag=tag), markdown1_end.format(tag=tag))

boundary1_chars = r'\s`!\'".,<>?*_~=' # slack to hangups

b1_left = r'(?:(?<=[' + boundary1_chars + r'])|(?<=^))'
b1_right = r'(?:(?=[' + boundary1_chars + r'])|(?=$))'

markdown1_start = b1_left + r'(?<!\\){tag}(?!\s)(?!{tag})'
markdown1_end = r'(?<!{tag})(?<!\s)(?<!\\){tag}' + b1_right

tokens_slack_to_hangups = [
    Token('b',          *markdown1(r'\*'),     is_bold=True),
    Token('i',          *markdown1(r'_'),      is_italic=True),
    Token('pre1',       *markdown1(r'`'),      skip=True),
    Token('pre2',       *markdown1(r'```'),    skip=True) ]

parser_slack_to_hangups = Parser(tokens_slack_to_hangups)

def render_link(link, label):
    if label in link:
        return link
    else:
        return link + " (" + label + ")"

def convert_slack_links(text):
    text = re.sub(r"<(.*?)\|(.*?)>",  lambda m: render_link(m.group(1), m.group(2)), text)
    return text

def slack_markdown_to_hangups(text, debug=False):
    lines = text.split("\n")
    nlines = []
    for line in lines:
        # workaround: for single char lines
        if len(line) < 2:
            line = line.replace("*", "\\*")
            line = line.replace("_", "\\_")
            nlines.append(line)
            continue

        # workaround: common pattern *<text>
        if re.match("^\*[^* ]", line) and line.count("*") % 2:
            line = line.replace("*", "* ", 1)

        # workaround: accidental consumption of * in "**test"
        replacement_token = "[2star:" + str(uuid.uuid4()) + "]"
        line = line.replace("**", replacement_token)

        segments = parser_slack_to_hangups.parse(line)

        nline=""
        for segment in [ (segment.text,
                          segment.params) for segment in segments ]:

            if debug: print(segment)

            text = segment[0]
            definition = segment[1]

            lspace = ""
            rspace = ""
            text = text.replace(replacement_token, "**")
            if text[0:1] == " ":
                lspace = " "
                text = text[1:]
            if text[-1:] == " ":
                rspace = " "
                text = text[:-1]

            # manually escape to prevent hangups markdown processing
            if "http" not in text:
                text = text.replace("*", "\\*")
                text = text.replace("_", "\\_")
            text = convert_slack_links(text)

            markdown = []
            if "is_bold" in definition and definition["is_bold"]:
                markdown.append("**")
            if "is_italic" in definition and definition["is_italic"]:
                markdown.append("_")

            nline += lspace
            nline += "".join(markdown)
            nline += text
            nline += "".join(markdown[::-1])
            nline += rspace

        nlines.append(nline)
    text = "\n".join(nlines)
    return text


if __name__ == '__main__':
    print("***SLACK MARKDOWN TO HANGUPS")
    print("")

    text = ('Hello *bold* world!\n'
            'You can *try _this_ awesome* [link](www.eff.org).\n'
            '*title*\n'
            '*hello\n'
            '* world\n'
            '*\n'
            '_\n'
            '*\n'
            '¯\_(ツ)_/¯\n'
            '<http://www.google.com.sg|Google Singapore> <http://www.google.com.my|Google Malaysia>\n'
            '<http://www.google.com|www.google.com>\n'
            'www.google.com\n'
            '**hello\n'
            '*** hi\n'
            '********\n'
            '_ xya kskdks')
    print(repr(text))
    print("")

    output = slack_markdown_to_hangups(text, debug=True)
    print("")

    print(repr(output))
    print("")

    print("***HANGUPS MARKDOWN TO SLACK PARSER")
    print("")

    text = ('**[bot] test markdown**\n'
            '**[ABCDEF ABCDEF](https://plus.google.com/u/0/1234567890/about)**\n'
            '... ([ABC@DEF.GHI](mailto:ABC@DEF.GHI))\n'
            '... 1234567890\n'
            '**[XYZ XYZ](https://plus.google.com/u/0/1234567890/about)**\n'
            '... 0123456789\n'
            '**`_Users: 2_`**\n'
            '**`ABC (xyz)`**, chat_id = _1234567890_' )
    print(repr(text))
    print("")

    output = get_formatted(text, SLACK_STYLE)
    print("")

    print(repr(output))
    print("")

