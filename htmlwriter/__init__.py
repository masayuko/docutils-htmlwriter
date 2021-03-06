# -*- coding: utf-8 -*-

# Author: David Goodger
# Maintainer: IGARASHI Masanao <syoux2@gmail.com>
# Copyright: This module has been placed in the public domain.

"""
Simple HyperText Markup Language document tree Writer.

The output conforms to the HTML.  The output contains a minimum of formatting
information.  The cascading style sheet "htmlwriter.css" is required
for proper viewing with a modern graphical browser.
"""

from __future__ import division

__docformat__ = 'reStructuredText'

try:
    unicode
except NameError:
    unicode = str

import sys
import os
import os.path
import time
import re
try:
    from urllib.request import url2pathname
except ImportError:
    from urllib import url2pathname
import io
try: # check for the Python Imaging Library
    import PIL.Image
except ImportError:
    try:  # sometimes PIL modules are put in PYTHONPATH's root
        import Image
        class PIL(object): pass  # dummy wrapper
        PIL.Image = Image
    except ImportError:
        PIL = None
import docutils
import docutils.io
from docutils import frontend, nodes, utils, writers, languages
from docutils.utils.error_reporting import SafeString
from docutils.transforms import writer_aux
from docutils.utils.math import unichar2tex, pick_math_environment, math2html
from docutils.utils.math.latex2mathml import parse_latex_math

class Writer(writers.Writer):

    supported = ('html', 'html5')
    """Formats this writer supports."""

    default_stylesheet = ['htmlwriter.css']
    default_stylesheet_dirs = ['.', os.path.abspath(os.path.dirname(__file__))]

    default_template = 'template.txt'
    default_template_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), default_template)

    settings_spec = (
        'HTML-Specific Options',
        None,
        (('Specify the template file (UTF-8 encoded).  Default is "%s".'
          % default_template_path,
          ['--template'],
          {'default': default_template_path, 'metavar': '<file>'}),
         ('Comma separated list of stylesheet URLs. '
          'Overrides previous --stylesheet and --stylesheet-path settings.',
          ['--stylesheet'],
          {'metavar': '<URL[,URL,...]>', 'overrides': 'stylesheet_path',
           'validator': frontend.validate_comma_separated_list}),
         ('Comma separated list of stylesheet paths. '
          'Relative paths are expanded if a matching file is found in '
          'the --stylesheet-dirs. With --link-stylesheet, '
          'the path is rewritten relative to the output HTML file. '
          'Default: "%s"' % ','.join(default_stylesheet),
          ['--stylesheet-path'],
          {'metavar': '<file[,file,...]>', 'overrides': 'stylesheet',
           'validator': frontend.validate_comma_separated_list,
           'default': default_stylesheet}),
         ('Embed the stylesheet(s) in the output HTML file.  The stylesheet '
          'files must be accessible during processing. This is the default.',
          ['--embed-stylesheet'],
          {'default': 1, 'action': 'store_true',
           'validator': frontend.validate_boolean}),
         ('Link to the stylesheet(s) in the output HTML file. '
          'Default: embed stylesheets.',
          ['--link-stylesheet'],
          {'dest': 'embed_stylesheet', 'action': 'store_false'}),
         ('Comma-separated list of directories where stylesheets are found. '
          'Used by --stylesheet-path when expanding relative path arguments. '
          'Default: "%s"' % default_stylesheet_dirs,
          ['--stylesheet-dirs'],
          {'metavar': '<dir[,dir,...]>',
           'validator': frontend.validate_comma_separated_list,
           'default': default_stylesheet_dirs}),
         ('Specify the initial header level.  Default is 1 for "<h1>".  '
          'Does not affect document title & subtitle (see --no-doc-title).',
          ['--initial-header-level'],
          {'choices': '1 2 3 4 5 6'.split(), 'default': '1',
           'metavar': '<level>'}),
         ('Specify the maximum width (in characters) for one-column field '
          'names.  Longer field names will span an entire row of the table '
          'used to render the field list.  Default is 14 characters.  '
          'Use 0 for "no limit".',
          ['--field-name-limit'],
          {'default': 14, 'metavar': '<level>',
           'validator': frontend.validate_nonnegative_int}),
         ('Specify the maximum width (in characters) for options in option '
          'lists.  Longer options will span an entire row of the table used '
          'to render the option list.  Default is 14 characters.  '
          'Use 0 for "no limit".',
          ['--option-limit'],
          {'default': 14, 'metavar': '<level>',
           'validator': frontend.validate_nonnegative_int}),
         ('Format for footnote references: one of "superscript" or '
          '"brackets".  Default is "brackets".',
          ['--footnote-references'],
          {'choices': ['superscript', 'brackets'], 'default': 'brackets',
           'metavar': '<format>',
           'overrides': 'trim_footnote_reference_space'}),
         ('Format for block quote attributions: one of "dash" (em-dash '
          'prefix), "parentheses"/"parens", or "none".  Default is "dash".',
          ['--attribution'],
          {'choices': ['dash', 'parentheses', 'parens', 'none'],
           'default': 'dash', 'metavar': '<format>'}),
         ('Remove extra vertical whitespace between items of "simple" bullet '
          'lists and enumerated lists.  Default: enabled.',
          ['--compact-lists'],
          {'default': 1, 'action': 'store_true',
           'validator': frontend.validate_boolean}),
         ('Disable compact simple bullet and enumerated lists.',
          ['--no-compact-lists'],
          {'dest': 'compact_lists', 'action': 'store_false'}),
         ('Remove extra vertical whitespace between items of simple field '
          'lists.  Default: enabled.',
          ['--compact-field-lists'],
          {'default': 1, 'action': 'store_true',
           'validator': frontend.validate_boolean}),
         ('Disable compact simple field lists.',
          ['--no-compact-field-lists'],
          {'dest': 'compact_field_lists', 'action': 'store_false'}),
         ('Added to standard table classes. '
          'Defined styles: "borderless". Default: ""',
          ['--table-style'],
          {'default': ''}),
         ('Math output format, one of "MathML", "HTML", "MathJax" '
          'or "LaTeX". Default: "HTML math.css"',
          ['--math-output'],
          {'default': 'HTML math.css'}),
         ('Omit the XML declaration.  Use with caution.',
          ['--no-xml-declaration'],
          {'dest': 'xml_declaration', 'default': 1, 'action': 'store_false',
           'validator': frontend.validate_boolean}),
         ('Obfuscate email addresses to confuse harvesters while still '
          'keeping email links usable with standards-compliant browsers.',
          ['--cloak-email-addresses'],
          {'action': 'store_true', 'validator': frontend.validate_boolean}),))

    settings_defaults = {'output_encoding_error_handler': 'xmlcharrefreplace'}

    config_section = 'html writer'
    config_section_dependencies = ('writers',)

    visitor_attributes = (
        'head_prefix', 'head', 'stylesheet', 'body_prefix',
        'body_pre_docinfo', 'docinfo', 'body', 'body_suffix',
        'title', 'subtitle', 'header', 'footer', 'meta', 'fragment',
        'html_prolog', 'html_head', 'html_title', 'html_subtitle',
        'html_body')

    def get_transforms(self):
        return writers.Writer.get_transforms(self) + [writer_aux.Admonitions]

    def __init__(self):
        writers.Writer.__init__(self)
        self.translator_class = HTMLTranslator

    def translate(self):
        self.visitor = visitor = self.translator_class(self.document)
        self.document.walkabout(visitor)
        for attr in self.visitor_attributes:
            setattr(self, attr, getattr(visitor, attr))
        self.output = self.apply_template()

    def apply_template(self):
        with io.open(self.document.settings.template, 'r',
                     encoding='utf-8') as f:
            template = f.read()
        subs = self.interpolation_dict()
        return template % subs

    def interpolation_dict(self):
        subs = {}
        settings = self.document.settings
        for attr in self.visitor_attributes:
            subs[attr] = ''.join(getattr(self, attr)).rstrip('\n')
        subs['encoding'] = settings.output_encoding
        subs['version'] = docutils.__version__
        return subs

    def assemble_parts(self):
        writers.Writer.assemble_parts(self)
        for part in self.visitor_attributes:
            self.parts[part] = ''.join(getattr(self, part))


class HTMLTranslator(nodes.NodeVisitor):

    """
    This HTML writer has been optimized to produce visually compact
    lists (less vertical whitespace).  HTML's mixed content models
    allow list items to contain "<li><p>body elements</p></li>" or
    "<li>just text</li>" or even "<li>text<p>and body
    elements</p>combined</li>", each with different effects.  It would
    be best to stick with strict body elements in list items, but they
    affect vertical spacing in browsers (although they really
    shouldn't).

    Here is an outline of the optimization:

    - Check for and omit <p> tags in "simple" lists: list items
      contain either a single paragraph, a nested simple list, or a
      paragraph followed by a nested simple list.  This means that
      this list can be compact:

          - Item 1.
          - Item 2.

      But this list cannot be compact:

          - Item 1.

            This second paragraph forces space between list items.

          - Item 2.

    - In non-list contexts, omit <p> tags on a paragraph if that
      paragraph is the only child of its parent (footnotes & citations
      are allowed a label first).

    - Regardless of the above, in definitions, table cells, field bodies,
      option descriptions, and list items, mark the first child with
      'class="first"' and the last child with 'class="last"'.  The stylesheet
      sets the margins (top & bottom respectively) to 0 for these elements.

    The ``no_compact_lists`` setting (``--no-compact-lists`` command-line
    option) disables list whitespace optimization.
    """

    xml_declaration = ''
    doctype = '<!DOCTYPE html>\n'
    doctype_mathml = doctype

    head_prefix_template = '<html lang="%(lang)s">\n'
    content_type = '<meta charset="%s">\n'

    generator = ('<meta name="generator" content="Docutils %s: '
                 'http://docutils.sourceforge.net/">\n')

    # Template for the MathJax script in the header:
    mathjax_script = '<script type="text/javascript" src="%s"></script>\n'
    # The latest version of MathJax from the distributed server:
    # avaliable to the public under the `MathJax CDN Terms of Service`__
    # __http://www.mathjax.org/download/mathjax-cdn-terms-of-service/
    mathjax_url = ('http://cdn.mathjax.org/mathjax/latest/MathJax.js?'
                   'config=TeX-AMS-MML_HTMLorMML')
    # may be overwritten by custom URL appended to "mathjax"

    stylesheet_link = '<link rel="stylesheet" href="%s">\n'
    embedded_stylesheet = '<style>\n\n%s\n</style>\n'
    words_and_spaces = re.compile(r'\S+| +|\n')
    # wrap point inside word
    sollbruchstelle = re.compile(r'.+\W\W.+|[-?].+', re.U)
    # name changes to the 'lang' attribute of the html tag
    lang_attribute = 'lang'

    # non-ascii [\n\r\t] non-ascii
    __RGX = re.compile(r'([^!-~])[\n\r\t]+([^!-~])')
    # non-ascii [\s]* <End-of-TEXT>
    __RGX1 = re.compile(r'([^!-~])[\s]*$')
    # <Beginning-of-TEXT> [\s]* non-ascii
    __RGX2 = re.compile(r'^[\s]*([^!-~])')

    def __init__(self, document):
        #super(HTMLTranslator, self).__init__(document)
        nodes.NodeVisitor.__init__(self, document)
        self.settings = settings = document.settings
        lcode = settings.language_code
        self.language = languages.get_language(lcode, document.reporter)
        self.meta = [self.generator % docutils.__version__]
        self.head_prefix = []
        self.html_prolog = []
        self.head = self.meta[:]
        self.stylesheet = [self.stylesheet_call(path)
                           for path in utils.get_stylesheet_list(settings)]
        self.body_prefix = ['</head>\n<body>\n']
        # document title, subtitle display
        self.body_pre_docinfo = []
        # author, date, etc.
        self.docinfo = []
        self.body = []
        self.fragment = []
        self.body_suffix = ['</body>\n</html>\n']
        self.section_level = 0
        self.initial_header_level = int(settings.initial_header_level)

        self.math_output = settings.math_output.split()
        self.math_output_options = self.math_output[1:]
        self.math_output = self.math_output[0].lower()

        # A heterogenous stack used in conjunction with the tree traversal.
        # Make sure that the pops correspond to the pushes:
        self.context = []

        self.topic_classes = [] # TODO: replace with self_in_contents
        self.colspecs = []
        self.compact_p = True
        self.compact_simple = False
        self.compact_field_list = False
        self.in_docinfo = False
        self.in_sidebar = False
        self.in_footnote_list = False
        self.title = []
        self.subtitle = []
        self.header = []
        self.footer = []
        self.html_head = [self.content_type] # charset not interpolated
        self.html_title = []
        self.html_subtitle = []
        self.html_body = []
        self.in_document_title = 0   # len(self.body) or 0
        self.in_mailto = False
        self.math_header = []
        self.protect_literal_text = False
        self.line_block_nest = 0

    def astext(self):
        return ''.join(self.head_prefix + self.head
                       + self.stylesheet + self.body_prefix
                       + self.body_pre_docinfo + self.docinfo
                       + self.body + self.body_suffix)

    def encode(self, text):
        """Encode special characters in `text` & return."""
        # Use only named entities known in HTML
        # other characters are automatically encoded "by number" if required.
        text = unicode(text)
        return text.translate({
            ord('&'): u'&amp;',
            ord('<'): u'&lt;',
            ord('"'): u'&quot;',
            ord('>'): u'&gt;',
            ord('@'): u'&#64;', # may thwart some address harvesters
            # TODO: convert non-breaking space only if needed?
            0xa0: u'&nbsp;'}) # non-breaking space

    def cloak_mailto(self, uri):
        """Try to hide a mailto: URL from harvesters."""
        # Encode "@" using a URL octet reference (see RFC 1738).
        # Further cloaking with HTML entities will be done in the
        # `attval` function.
        return uri.replace('@', '%40')

    def cloak_email(self, addr):
        """Try to hide the link text of a email link from harvesters."""
        # Surround at-signs and periods with <span> tags.  ("@" has
        # already been encoded to "&#64;" by the `encode` method.)
        addr = addr.replace('&#64;', '<span>&#64;</span>')
        addr = addr.replace('.', '<span>&#46;</span>')
        return addr

    def attval(self, text,
               whitespace=re.compile('[\n\r\t\v\f]')):
        """Cleanse, HTML encode, and return attribute value text."""
        encoded = self.encode(whitespace.sub(' ', text))
        if self.in_mailto and self.settings.cloak_email_addresses:
            # Cloak at-signs ("%40") and periods with HTML entities.
            encoded = encoded.replace('%40', '&#37;&#52;&#48;')
            encoded = encoded.replace('.', '&#46;')
        return encoded

    def stylesheet_call(self, path):
        """Return code to reference or embed stylesheet file `path`"""
        if self.settings.embed_stylesheet:
            try:
                content = docutils.io.FileInput(source_path=path,
                                                encoding='utf-8').read()
                self.settings.record_dependencies.add(path)
            except IOError as err:
                msg = u"Cannot embed stylesheet '%s': %s." % (
                                path, SafeString(err.strerror))
                self.document.reporter.error(msg)
                return '<--- %s --->\n' % msg
            return self.embedded_stylesheet % content
        # else link to style file:
        if self.settings.stylesheet_path:
            # adapt path relative to output (cf. config.html#stylesheet-path)
            path = utils.relative_path(self.settings._destination, path)
        return self.stylesheet_link % self.encode(path)

    def starttag(self, node, tagname, suffix='\n', empty=False, **attributes):
        """
        Construct and return a start tag given a node (id & class attributes
        are extracted), tag name, and optional attributes.
        """
        tagname = tagname.lower()
        prefix = []
        atts = {}
        ids = []
        for (name, value) in attributes.items():
            atts[name.lower()] = value
        classes = []
        languages = []
        # unify class arguments and move language specification
        for cls in node.get('classes', []) + atts.pop('class', '').split() :
            if cls.startswith('language-'):
                languages.append(cls[9:])
            elif cls.strip() and cls not in classes:
                classes.append(cls)
        if languages:
            atts[self.lang_attribute] = languages[0]
        if classes:
            atts['class'] = ' '.join(classes)
        assert 'id' not in atts
        ids.extend(node.get('ids', []))
        if 'ids' in atts:
            ids.extend(atts['ids'])
            del atts['ids']
        if ids:
            atts['id'] = ids[0]
            for id in ids[1:]:
                # Add empty "span" elements for additional IDs.  Note
                # that we cannot use empty "a" elements because there
                # may be targets inside of references, but nested "a"
                # elements aren't allowed in XHTML (even if they do
                # not all have a "href" attribute).
                if empty:
                    # Empty tag.  Insert target right in front of element.
                    prefix.append('<span id="%s"></span>' % id)
                else:
                    # Non-empty tag.  Place the auxiliary <span> tag
                    # *inside* the element, as the first child.
                    suffix += '<span id="%s"></span>' % id
        parts = [tagname]
        for name, value in sorted(atts.items()):
            if value is None:
                parts.append(name.lower())
            else:
                if isinstance(value, list):
                    vals = self.attval(' '.join(value))
                else:
                    vals = value
                parts.append('%s="%s"' % (name.lower(), vals))
        return ''.join(prefix) + '<%s>' % (' '.join(parts),) + suffix

    def emptytag(self, node, tagname, suffix='\n', **attributes):
        """Construct and return an XML-compatible empty tag."""
        return self.starttag(node, tagname, suffix, empty=True, **attributes)

    def set_class_on_child(self, node, class_, index=0):
        """
        Set class `class_` on the visible child no. index of `node`.
        Do nothing if node has fewer children than `index`.
        """
        children = [n for n in node if not isinstance(n, nodes.Invisible)]
        try:
            child = children[index]
        except IndexError:
            return
        child['classes'].append(class_)

    def visit_Text(self, node):
        text = node.astext()
        encoded = self.encode(text)
        if self.protect_literal_text or self.line_block_nest:
            # moved here from base class's visit_literal to support
            # more formatting in literal nodes
            for token in self.words_and_spaces.findall(encoded):
                if token.strip():
                    # protect literal text from line wrapping
                    self.body.append('<span class="pre">%s</span>' % token)
                elif token in ' \n':
                    # allow breaks at whitespace
                    self.body.append(token)
                else:
                    # protect runs of multiple spaces; the last one can wrap
                    self.body.append('&nbsp;' * (len(token)-1) + ' ')
        else:
            if self.in_mailto and self.settings.cloak_email_addresses:
                encoded = self.cloak_email(encoded)
            self.body.append(encoded)

    def depart_Text(self, node):
        pass

    def visit_abbreviation(self, node):
        # @@@ implementation incomplete ("title" attribute)
        self.body.append(self.starttag(node, 'abbr', ''))

    def depart_abbreviation(self, node):
        self.body.append('</abbr>')

    def visit_acronym(self, node):
        # @@@ implementation incomplete ("title" attribute)
        self.body.append(self.starttag(node, 'abbr', ''))

    def depart_acronym(self, node):
        self.body.append('</abbr>')

    def visit_address(self, node):
        self.visit_docinfo_item(node, 'address', meta=False)
        self.body.append(self.starttag(node, 'pre', CLASS='address'))

    def depart_address(self, node):
        self.body.append('\n</pre>\n')
        self.depart_docinfo_item()

    def visit_admonition(self, node):
        node['classes'].insert(0, 'admonition')
        self.body.append(self.starttag(node, 'div'))

    def depart_admonition(self, node=None):
        self.body.append('</div>\n')

    attribution_formats = {'dash': (u'\u2014', ''),
                           'parentheses': ('(', ')'),
                           'parens': ('(', ')'),
                           'none': ('', '')}

    def visit_attribution(self, node):
        prefix, suffix = self.attribution_formats[self.settings.attribution]
        self.context.append(suffix)
        self.body.append(
            self.starttag(node, 'p', prefix, CLASS='attribution'))
        self.body.append(self.starttag(node, 'cite', ''))

    def depart_attribution(self, node):
        self.body.append('</cite>' + self.context.pop() + '</p>\n')

    # author, authors
    # ---------------
    # Use paragraphs instead of hard-coded linebreaks.

    def visit_author(self, node):
        if not(isinstance(node.parent, nodes.authors)):
            self.visit_docinfo_item(node, 'author')
        self.body.append('<p>')

    def depart_author(self, node):
        self.body.append('</p>')
        if isinstance(node.parent, nodes.authors):
            self.body.append('\n')
        else:
            self.depart_docinfo_item()

    def visit_authors(self, node):
        self.visit_docinfo_item(node, 'authors', meta=False)

    def depart_authors(self, node):
        self.depart_docinfo_item()

    def visit_block_quote(self, node):
        self.body.append(self.starttag(node, 'blockquote'))

    def depart_block_quote(self, node):
        self.body.append('</blockquote>\n')

    def check_simple_list(self, node):
        """Check for a simple list that can be rendered compactly."""
        visitor = SimpleListChecker(self.document)
        try:
            node.walk(visitor)
        except nodes.NodeFound:
            return None
        else:
            return 1

    # Compact lists
    # ------------
    # Include definition lists and field lists (in addition to ordered
    # and unordered lists) in the test if a list is "simple"  (cf. the
    # html4css1.HTMLTranslator docstring and the SimpleListChecker class at
    # the end of this file).

    def is_compactable(self, node):
        # explicite class arguments have precedence
        if 'compact' in node['classes']:
            return True
        if 'open' in node['classes']:
            return False
        # check config setting:
        if (isinstance(node, nodes.field_list) or
            isinstance(node, nodes.definition_list)
           ) and not self.settings.compact_field_lists:
            return False
        if (isinstance(node, nodes.enumerated_list) or
            isinstance(node, nodes.bullet_list)
           ) and not self.settings.compact_lists:
            return False
        # more special cases:
        if (self.topic_classes == ['contents']): # TODO: self.in_contents
            return True
        # check the list items:
        visitor = SimpleListChecker(self.document)
        try:
            node.walk(visitor)
        except nodes.NodeFound:
            return False
        else:
            return True

    def visit_bullet_list(self, node):
        atts = {}
        old_compact_simple = self.compact_simple
        self.context.append((self.compact_simple, self.compact_p))
        self.compact_p = None
        self.compact_simple = self.is_compactable(node)
        if self.compact_simple and not old_compact_simple:
            atts['class'] = 'simple'
        self.body.append(self.starttag(node, 'ul', **atts))

    def depart_bullet_list(self, node):
        self.compact_simple, self.compact_p = self.context.pop()
        self.body.append('</ul>\n')

    def visit_caption(self, node):
        self.body.append(self.starttag(node, 'figcaption', ''))

    def depart_caption(self, node):
        self.body.append('</figcaption>\n')

    # citations
    # ---------
    # Use definition list instead of table for bibliographic references.
    # Join adjacent citation entries.

    def visit_citation(self, node):
        if not self.in_footnote_list:
            self.body.append('<dl class="citation">\n')
            self.in_footnote_list = True

    def depart_citation(self, node):
        self.body.append('</dd>\n')
        if not isinstance(node.next_node(descend=False, siblings=True),
                          nodes.citation):
            self.body.append('</dl>\n')
            self.in_footnote_list = False

    def visit_citation_reference(self, node):
        href = '#'
        if 'refid' in node:
            href += node['refid']
        elif 'refname' in node:
            href += self.document.nameids[node['refname']]
        # else: # TODO system message (or already in the transform)?
        # 'Citation reference missing.'
        self.body.append(self.starttag(
            node, 'a', '[', CLASS='citation-reference', href=href))

    def depart_citation_reference(self, node):
        self.body.append(']</a>')

    # classifier
    # ----------
    # don't insert classifier-delimiter here (done by CSS)

    def visit_classifier(self, node):
        self.body.append(self.starttag(node, 'span', '', CLASS='classifier'))

    def depart_classifier(self, node):
        self.body.append('</span>')

    def visit_colspec(self, node):
        self.colspecs.append(node)
        # "stubs" list is an attribute of the tgroup element:
        node.parent.stubs.append(node.attributes.get('stub'))

    def depart_colspec(self, node):
        pass

    def write_colspecs(self):
        width = 0
        for node in self.colspecs:
            width += node['colwidth']
        for node in self.colspecs:
            colwidth = int(node['colwidth'] * 100.0 / width + 0.5)
            self.body.append(self.emptytag(node, 'col',
                                           style='width:%i%%' % colwidth))
        self.colspecs = []

    def visit_comment(self, node,
                      sub=re.compile('-(?=-)').sub):
        """Escape double-dashes in comment text."""
        self.body.append('<!-- %s -->\n' % sub('- ', node.astext()))
        # Content already processed:
        raise nodes.SkipNode

    def visit_compound(self, node):
        self.body.append(self.starttag(node, 'div', CLASS='compound'))
        if len(node) > 1:
            node[0]['classes'].append('compound-first')
            node[-1]['classes'].append('compound-last')
            for child in node[1:-1]:
                child['classes'].append('compound-middle')

    def depart_compound(self, node):
        self.body.append('</div>\n')

    def visit_container(self, node):
        self.body.append(self.starttag(node, 'div', CLASS='docutils container'))

    def depart_container(self, node):
        self.body.append('</div>\n')

    def visit_contact(self, node):
        self.visit_docinfo_item(node, 'contact', meta=False)

    def depart_contact(self, node):
        self.depart_docinfo_item()

    def visit_copyright(self, node):
        self.visit_docinfo_item(node, 'copyright', meta=False)

    def depart_copyright(self, node):
        self.depart_docinfo_item()

    def visit_date(self, node):
        self.visit_docinfo_item(node, 'date', meta=False)

    def depart_date(self, node):
        self.depart_docinfo_item()

    def visit_decoration(self, node):
        pass

    def depart_decoration(self, node):
        pass

    def visit_definition(self, node):
        self.body.append('</dt>\n')
        self.body.append(self.starttag(node, 'dd', ''))

    def depart_definition(self, node):
        self.body.append('</dd>\n')

    def visit_definition_list(self, node):
        classes = node.setdefault('classes', [])
        if self.is_compactable(node):
            classes.append('simple')
        self.body.append(self.starttag(node, 'dl'))

    def depart_definition_list(self, node):
        self.body.append('</dl>\n')

    def visit_definition_list_item(self, node):
        # pass class arguments, ids and names to definition term:
        node.children[0]['classes'] = (
            node.get('classes', []) + node.children[0].get('classes', []))
        node.children[0]['ids'] = (
            node.get('ids', []) + node.children[0].get('ids', []))
        node.children[0]['names'] = (
            node.get('names', []) + node.children[0].get('names', []))

    def depart_definition_list_item(self, node):
        pass

    def visit_description(self, node):
        self.body.append(self.starttag(node, 'dd', ''))

    def depart_description(self, node):
        self.body.append('</dd>\n')

    # docinfo
    # -------
    # use definition list instead of table

    def visit_docinfo(self, node):
        classes = 'docinfo'
        if (self.is_compactable(node)):
            classes += ' simple'
        self.body.append(self.starttag(node, 'dl', CLASS=classes))

    def depart_docinfo(self, node):
        self.body.append('</dl>\n')

    def visit_docinfo_item(self, node, name, meta=True):
        if meta:
            meta_tag = '<meta name="%s" content="%s">\n' \
                       % (name, self.attval(node.astext()))
            self.add_meta(meta_tag)
        self.body.append('<dt class="%s">%s</dt>\n'
                         % (name, self.language.labels[name]))
        self.body.append(self.starttag(node, 'dd', '', CLASS=name))

    def depart_docinfo_item(self):
        self.body.append('</dd>\n')

    def visit_doctest_block(self, node):
        self.body.append(self.starttag(node, 'pre', suffix='',
                                       CLASS='code python doctest'))

    def depart_doctest_block(self, node):
        self.body.append('\n</pre>\n')

    def visit_document(self, node):
        self.head.append('<title>%s</title>\n'
                         % self.encode(node.get('title', '')))

    def depart_document(self, node):
        self.head_prefix.extend([self.doctype,
                                 self.head_prefix_template %
                                 {'lang': self.settings.language_code}])
        self.html_prolog.append(self.doctype)
        self.meta.insert(0, self.content_type % self.settings.output_encoding)
        self.head.insert(0, self.content_type % self.settings.output_encoding)
        if self.math_header:
            if self.math_output == 'mathjax':
                self.head.extend(self.math_header)
            else:
                self.stylesheet.extend(self.math_header)
        # skip content-type meta tag with interpolated charset value:
        self.html_head.extend(self.head[1:])
        self.body_prefix.append(self.starttag(node, 'div', CLASS='document'))
        self.body_suffix.insert(0, '</div>\n')
        self.fragment.extend(self.body) # self.fragment is the "naked" body
        self.html_body.extend(self.body_prefix[1:] + self.body_pre_docinfo
                              + self.docinfo + self.body
                              + self.body_suffix[:-1])
        assert not self.context, 'len(context) = %s' % len(self.context)

    def visit_emphasis(self, node):
        self.body.append(self.starttag(node, 'em', ''))

    def depart_emphasis(self, node):
        self.body.append('</em>')

    def visit_entry(self, node):
        atts = {'class': []}
        if isinstance(node.parent.parent, nodes.thead):
            atts['class'].append('head')
        if node.parent.parent.parent.stubs[node.parent.column]:
            # "stubs" list is an attribute of the tgroup element
            atts['class'].append('stub')
        if atts['class']:
            tagname = 'th'
            atts['class'] = ' '.join(atts['class'])
        else:
            tagname = 'td'
            del atts['class']
        node.parent.column += 1
        if 'morerows' in node:
            atts['rowspan'] = node['morerows'] + 1
        if 'morecols' in node:
            atts['colspan'] = node['morecols'] + 1
            node.parent.column += node['morecols']
        self.body.append(self.starttag(node, tagname, '', **atts))
        self.context.append('</%s>\n' % tagname.lower())
        # TODO: why did the html4css1 writer insert an NBSP into empty cells?
        # if len(node) == 0:              # empty cell
        #     self.body.append('&nbsp;')

    def depart_entry(self, node):
        self.body.append(self.context.pop())

    def visit_enumerated_list(self, node):
        atts = {}
        if 'start' in node:
            atts['start'] = node['start']
        if 'enumtype' in node:
            atts['class'] = node['enumtype']
        if self.is_compactable(node):
            atts['class'] = (atts.get('class', '') + ' simple').strip()
        self.body.append(self.starttag(node, 'ol', **atts))

    def depart_enumerated_list(self, node):
        self.body.append('</ol>\n')

    def visit_field(self, node):
        pass

    def depart_field(self, node):
        pass

    def visit_field_body(self, node):
        self.body.append(self.starttag(node, 'dd', '',
                                       CLASS=''.join(node.parent['classes'])))

    def depart_field_body(self, node):
        self.body.append('</dd>\n')

    # field-list
    # ----------
    # set as definition list, styled with CSS

    def visit_field_list(self, node):
        # Keep simple paragraphs in the field_body to enable CSS
        # rule to start body on new line if the label is too long
        classes = 'field-list'
        if (self.is_compactable(node)):
            classes += ' simple'
        self.body.append(self.starttag(node, 'dl', CLASS=classes))

    def depart_field_list(self, node):
        self.body.append('</dl>\n')

    # as field is ignored, pass class arguments to field-name and field-body:

    def visit_field_name(self, node):
        self.body.append(self.starttag(node, 'dt', '',
                                       CLASS=''.join(node.parent['classes'])))

    def depart_field_name(self, node):
        self.body.append('</dt>\n')

    def visit_figure(self, node):
        atts = {}
        styles = {}

        if 'figwidth' in node:
            styles['width'] = node['figwidth']

        halign = ''
        if 'align' in node:
            for alignval in [x.strip() for x in node['align'].split(',')]:
                if alignval in ('left', 'right', 'center'):
                    halign = alignval

        styles['vertical-align'] = 'bottom'

        if isinstance(node.parent, nodes.reference):
            # Inline context or surrounded by <a>...</a>.
            suffix = ''
            self.context.append('</figure>')
        else:
            suffix = '\n'
            if halign in ('left', 'right'):
                self.body.append(
                    '<div class="align-%s" style="height:auto">\n' % halign)
            elif halign == 'center':
                self.body.append(
                    '<div style="height:auto;margin:16px auto;display:table">' +
                    '\n')
            else:
                self.body.append('<div style="height:auto">\n')
            self.context.append('</figure></div>\n')

        style = ''
        for style_name, style_value in styles.items():
            style += '{}:{};'.format(style_name, style_value)
        if style:
            atts['style'] = style
        self.body.append(self.emptytag(node, 'figure', suffix, **atts))

    def depart_figure(self, node):
        self.body.append(self.context.pop())

    # use HTML 5 <footer> element?
    def visit_footer(self, node):
        self.context.append(len(self.body))

    def depart_footer(self, node):
        start = self.context.pop()
        footer = [self.starttag(node, 'div', CLASS='footer'),
                  '<hr class="footer">\n']
        footer.extend(self.body[start:])
        footer.append('\n</div>\n')
        self.footer.extend(footer)
        self.body_suffix[:0] = footer
        del self.body[start:]

    # footnotes
    # ---------
    # use definition list instead of table for footnote text

    def visit_footnote(self, node):
        if not self.in_footnote_list:
            classes = 'footnote ' + self.settings.footnote_references
            self.body.append('<dl class="%s">\n'%classes)
            self.in_footnote_list = True

    def depart_footnote(self, node):
        self.body.append('</dd>\n')
        if not isinstance(node.next_node(descend=False, siblings=True),
                          nodes.footnote):
            self.body.append('</dl>\n')
            self.in_footnote_list = False

    def visit_footnote_reference(self, node):
        href = '#' + node['refid']
        classes = 'footnote-reference ' + self.settings.footnote_references
        self.body.append(self.starttag(node, 'a', '', #suffix,
                                       CLASS=classes, href=href))

    def depart_footnote_reference(self, node):
        self.body.append('</a>')

    def visit_generated(self, node):
        if 'sectnum' in node['classes']:
            # get section number (strip trailing no-break-spaces)
            sectnum = node.astext().rstrip(u' ')
            self.body.append('<span class="sectnum">%s</span> '
                                    % self.encode(sectnum))
            # Content already processed:
            raise nodes.SkipNode

    def depart_generated(self, node):
        pass

    def visit_header(self, node):
        self.context.append(len(self.body))

    def depart_header(self, node):
        start = self.context.pop()
        header = [self.starttag(node, 'div', CLASS='header')]
        header.extend(self.body[start:])
        header.append('\n<hr class="header"/>\n</div>\n')
        self.body_prefix.extend(header)
        self.header.extend(header)
        del self.body[start:]

    def get_value_with_unit(self, value):
        match = re.match(r'([0-9.]+)(\S*)$', value)
        assert match
        unit =  match.group(2)
        if not unit:
            # Interpret unitless values as pixels.
            unit = 'px'
        return match.group(1), unit

    def visit_image(self, node):
        atts = {}
        uri = node['uri']
        ext = os.path.splitext(uri)[1].lower()
        styles = {}
        units = {}

        for att_name in ('width', 'height'):
            if att_name in node:
                value, unit = self.get_value_with_unit(node[att_name])
                if unit == 'px':
                    atts[att_name] = value
                units[att_name] = (value, unit)

        if 'scale' in node:
            if (PIL and not ('width' in atts and 'height' in atts)
                and self.settings.file_insertion_enabled):
                imagepath = url2pathname(uri)
                try:
                    img = PIL.Image.open(
                            imagepath.encode(sys.getfilesystemencoding()))
                except (IOError, UnicodeEncodeError):
                    pass # TODO: warn?
                else:
                    self.settings.record_dependencies.add(
                        imagepath.replace('\\', '/'))
                    atts['width'] = str(img.size[0])
                    atts['height'] = str(img.size[1])
                    del img

            scale = float(node['scale'])

            if 'width' in units:
                styles['width'] = '{:d}{}'.format(
                    int(float(units['width'][0]) * scale // 100),
                    units['width'][1])
            if 'height' in units:
                styles['height'] = '{:d}{}'.format(
                    int(float(units['height'][0]) * scale // 100),
                    units['height'][1])

            if not ('width' in styles or not 'height' in styles):
                if 'width' in atts:
                    styles['width'] = '{:d}px'.format(
                        int(float(atts['width']) * scale // 100))
                if 'height' in atts:
                    styles['height'] = '{:d}px'.format(
                        int(float(atts['height']) * scale // 100))

            if 'width' in styles and not 'height' in styles:
                styles['height'] = 'auto'
            elif not 'width' in styles and 'height' in styles:
                styles['width'] = 'auto'
            elif not 'width' in styles and not 'height' in styles:
                styles['max-width'] = '{:d}%'.format(int(scale))
                styles['height'] = 'auto'
        else:
            if 'width' in units:
                styles['width'] = '{:d}{}'.format(int(units['width'][0]),
                                                  units['width'][1])
            if 'height' in units:
                styles['height'] = '{:d}{}'.format(int(units['height'][0]),
                                                   units['height'][1])
            if 'width' in styles and not 'height' in styles:
                styles['height'] = 'auto'
            elif not 'width' in styles and 'height' in styles:
                styles['width'] = 'auto'
            elif not 'width' in styles and not 'height' in styles:
                styles['max-width'] = '100%'
                styles['height'] = 'auto'

        valign = ''
        halign = ''
        if 'align' in node:
            for alignval in [x.strip() for x in node['align'].split(',')]:
                if alignval in ('left', 'right', 'center'):
                    halign = alignval
                if alignval in ('top', 'bottom', 'middle'):
                    valign = alignval

        if valign:
            styles['vertical-align'] = valign
        else:
            styles['vertical-align'] = 'bottom'

        if (isinstance(node.parent, nodes.reference) or
            isinstance(node.parent, nodes.figure)):
            # Inline context or surrounded by <a>...</a>.
            suffix = ''
            self.context.append('')
        else:
            suffix = '\n'
            if halign in ('left', 'right'):
                self.body.append(
                    '<div class="align-%s" style="height:auto">\n' % halign)
            elif halign == 'center':
                self.body.append(
                    '<div style="height:auto;margin:16px auto;display:table">' +
                    '\n')
            else:
                self.body.append('<div style="height:auto">\n')
            self.context.append('</div>\n')

        style = ''
        for style_name, style_value in styles.items():
            style += '{}:{};'.format(style_name, style_value)
        atts['style'] = style

        # place SWF images in an <object> element
        if ext == 'swf':
            atts['data'] = uri
            atts['type'] = 'application/x-shockwave-flash'
            self.body.append(self.starttag(node, 'object', **atts) +
                             '<param name="movie" value="{}">'.format(uri) +
                             '<embed src="%s">'.format(uri) +
                             '</embed></object>' + suffix)
        else:
            atts['src'] = uri
            atts['alt'] = node.get('alt', uri)
            self.body.append(self.emptytag(node, 'img', suffix, **atts))

    def depart_image(self, node):
        self.body.append(self.context.pop())

    def visit_inline(self, node):
        self.body.append(self.starttag(node, 'span', ''))

    def depart_inline(self, node):
        self.body.append('</span>')

    # footnote and citation label
    def label_delim(self, node, bracket, superscript):
        """put brackets around label?"""
        if isinstance(node.parent, nodes.footnote):
            if self.settings.footnote_references == 'brackets':
                return bracket
            else:
                return superscript
        assert isinstance(node.parent, nodes.citation)
        return bracket

    def visit_label(self, node):
        if (isinstance(node.parent, nodes.footnote)):
            classes = self.settings.footnote_references
        else:
            classes = 'brackets'
        # pass parent node to get id into starttag:
        self.body.append(self.starttag(node.parent, 'dt', '', CLASS='label'))
        self.body.append(self.starttag(node, 'span', '', CLASS=classes))
        # footnote/citation backrefs:
        if self.settings.footnote_backlinks:
            backrefs = node.parent['backrefs']
            if len(backrefs) == 1:
                self.body.append('<a class="fn-backref" href="#%s">'
                                 % backrefs[0])

    def depart_label(self, node):
        self.body.append('</span>')
        if self.settings.footnote_backlinks:
            backrefs = node.parent['backrefs']
            if len(backrefs) == 1:
                self.body.append('</a>')
            elif len(backrefs) > 1:
                # Python 2.4 fails with enumerate(backrefs, 1)
                backlinks = ['<a href="#%s">%s</a>' % (ref, i+1)
                             for (i, ref) in enumerate(backrefs)]
                self.body.append('<span class="fn-backref">(%s)</span>'
                                 % ','.join(backlinks))
        self.body.append('</dt>\n<dd>')

    def visit_legend(self, node):
        self.body.append(self.starttag(node, 'div', CLASS='legend'))

    def depart_legend(self, node):
        self.body.append('</div>\n')

    def visit_line(self, node):
        pass

    def depart_line(self, node):
        self.body.append('<br>\n')

    def visit_line_block(self, node):
        self.body.append(self.starttag(node, 'div', CLASS='line-block'))
        self.line_block_nest += 1

    def depart_line_block(self, node):
        self.line_block_nest -= 1
        self.body.append('</div>\n')

    def visit_list_item(self, node):
        self.body.append(self.starttag(node, 'li', ''))

    def depart_list_item(self, node):
        self.body.append('</li>\n')

    def visit_literal(self, node):
        self.body.append(self.starttag(node, 'code', '',
                                       CLASS='docutils literal'))
        self.protect_literal_text = True

    def depart_literal(self, node):
        self.protect_literal_text = False
        self.body.append('</code>')

    def visit_literal_block(self, node):
        self.body.append(self.starttag(node, 'pre', CLASS='literal-block'))
        if 'code' in node.get('classes', []):
            self.body.append('<code>')

    def depart_literal_block(self, node):
        if 'code' in node.get('classes', []):
            self.body.append('</code>')
        self.body.append('\n</pre>\n')

    def visit_math(self, node, math_env=''):
        # If the method is called from visit_math_block(), math_env != ''.

        # As there is no native HTML math support, we provide alternatives:
        # LaTeX and MathJax math_output modes simply wrap the content,
        # HTML and MathML math_output modes also convert the math_code.
        if self.math_output not in ('mathml', 'html', 'mathjax', 'latex'):
            self.document.reporter.error(
                'math-output format "%s" not supported '
                'falling back to "latex"'% self.math_output)
            self.math_output = 'latex'
        #
        # HTML container
        tags = {# math_output: (block, inline, class-arguments)
                'mathml':      ('div', '', ''),
                'html':        ('div', 'span', 'formula'),
                'mathjax':     ('div', 'span', 'math'),
                'latex':       ('pre', 'tt',   'math'),
               }
        tag = tags[self.math_output][math_env == '']
        clsarg = tags[self.math_output][2]
        # LaTeX container
        wrappers = {# math_mode: (inline, block)
                    'mathml':  (None,     None),
                    'html':    ('$%s$',   u'\\begin{%s}\n%s\n\\end{%s}'),
                    'mathjax': ('\(%s\)', u'\\begin{%s}\n%s\n\\end{%s}'),
                    'latex':   (None,     None),
                   }
        wrapper = wrappers[self.math_output][math_env != '']
        # get and wrap content
        math_code = node.astext().translate(unichar2tex.uni2tex_table)
        if wrapper and math_env:
            math_code = wrapper % (math_env, math_code, math_env)
        elif wrapper:
            math_code = wrapper % math_code
        # settings and conversion
        if self.math_output in ('latex', 'mathjax'):
            math_code = self.encode(math_code)
        if self.math_output == 'mathjax' and not self.math_header:
            if self.math_output_options:
                self.mathjax_url = self.math_output_options[0]
            self.math_header = [self.mathjax_script % self.mathjax_url]
        elif self.math_output == 'html':
            if self.math_output_options and not self.math_header:
                self.math_header = [self.stylesheet_call(
                    utils.find_file_in_dirs(s, self.settings.stylesheet_dirs))
                    for s in self.math_output_options[0].split(',')]
            # TODO: fix display mode in matrices and fractions
            math2html.DocumentParameters.displaymode = (math_env != '')
            math_code = math2html.math2html(math_code)
        elif self.math_output == 'mathml':
            self.doctype = self.doctype_mathml
            try:
                mathml_tree = parse_latex_math(math_code, inline=not(math_env))
                math_code = ''.join(mathml_tree.xml())
            except SyntaxError as err:
                err_node = self.document.reporter.error(err, base_node=node)
                self.visit_system_message(err_node)
                self.body.append(self.starttag(node, 'p'))
                self.body.append(u','.join(err.args))
                self.body.append('</p>\n')
                self.body.append(self.starttag(node, 'pre',
                                               CLASS='literal-block'))
                self.body.append(self.encode(math_code))
                self.body.append('\n</pre>\n')
                self.depart_system_message(err_node)
                raise nodes.SkipNode
        # append to document body
        if tag:
            self.body.append(self.starttag(node, tag,
                                           suffix='\n'*bool(math_env),
                                           CLASS=clsarg))
        self.body.append(math_code)
        if math_env: # block mode (equation, display)
            self.body.append('\n')
        if tag:
            self.body.append('</%s>' % tag)
        if math_env:
            self.body.append('\n')
        # Content already processed:
        raise nodes.SkipNode

    def depart_math(self, node):
        pass # never reached

    def visit_math_block(self, node):
        math_env = pick_math_environment(node.astext())
        self.visit_math(node, math_env=math_env)

    def depart_math_block(self, node):
        pass # never reached

    def visit_meta(self, node):
        meta = self.emptytag(node, 'meta', **node.non_default_attributes())
        self.add_meta(meta)

    def depart_meta(self, node):
        pass

    def add_meta(self, tag):
        self.meta.append(tag)
        self.head.append(tag)

    def visit_option(self, node):
        self.body.append(self.starttag(node, 'span', '', CLASS='option'))

    def depart_option(self, node):
        self.body.append('</span>')
        if isinstance(node.next_node(descend=False, siblings=True),
                      nodes.option):
            self.body.append(', ')

    def visit_option_argument(self, node):
        self.body.append(node.get('delimiter', ' '))
        self.body.append(self.starttag(node, 'var', ''))

    def depart_option_argument(self, node):
        self.body.append('</var>')

    def visit_option_group(self, node):
        self.body.append(self.starttag(node, 'dt', ''))
        self.body.append('<kbd>')

    def depart_option_group(self, node):
        self.body.append('</kbd></dt>\n')

    def visit_option_list(self, node):
        self.body.append(
            self.starttag(node, 'dl', CLASS='option-list'))

    def depart_option_list(self, node):
        self.body.append('</dl>\n')

    def visit_option_list_item(self, node):
        pass

    def depart_option_list_item(self, node):
        pass

    def visit_option_string(self, node):
        pass

    def depart_option_string(self, node):
        pass

    def visit_organization(self, node):
        self.visit_docinfo_item(node, 'organization', meta=False)

    def depart_organization(self, node):
        self.depart_docinfo_item()

    def strip_spaces_between_uchars(self, para):
        # modify text inside Text node
        for node in para.traverse():
            if isinstance(node, docutils.nodes.Text):
                newtext = node.astext()
                newtext = self.__RGX.sub(r"\1\2", newtext)
                node.parent.replace(node, docutils.nodes.Text(newtext))

    def strip_spaces_around_uchars_paragraph_children(self, para):
        # modify texts over 2 nodes
        # (paragraph node can have childre of Inline (reference, etc) nodes)
        prev_textnode = docutils.nodes.Text("")
        for node in para.traverse():
            new_textnode = None
            if isinstance(node, docutils.nodes.Text):
                prevtext = prev_textnode.astext()
                newtext = node.astext()
                if self.__RGX1.search(prevtext) and self.__RGX2.search(newtext):
                    new_prev_textnode = docutils.nodes.Text(
                        prev_textnode.astext().rstrip())
                    new_textnode = Text(newtext.lstrip())
                    prev_textnode.parent.replace(prev_textnode,
                                                 new_prev_textnode)
                    node.parent.replace(node, new_textnode)
                    new_prev_textnode.parent = prev_textnode.parent
                    new_textnode.parent = node.parent
                prev_textnode = new_textnode if new_textnode else node

    # Do not omit <p> tags
    # --------------------
    #
    # The HTML4CSS1 writer does this to "produce
    # visually compact lists (less vertical whitespace)". This writer
    # relies on CSS rules for"visual compactness".
    #
    # * In XHTML 1.1, e.g. a <blockquote> element may not contain
    #   character data, so you cannot drop the <p> tags.
    # * Keeping simple paragraphs in the field_body enables a CSS
    #   rule to start the field-body on a new line if the label is too long
    # * it makes the code simpler.
    #
    # TODO: omit paragraph tags in simple table cells?

    def visit_paragraph(self, node):
        self.strip_spaces_between_uchars(node)
        self.strip_spaces_around_uchars_paragraph_children(node)
        self.body.append(self.starttag(node, 'p', ''))

    def depart_paragraph(self, node):
        self.body.append('</p>')
        if not (isinstance(node.parent, (nodes.list_item, nodes.entry)) and
                (len(node.parent) == 1)):
            self.body.append('\n')

    def visit_problematic(self, node):
        if node.hasattr('refid'):
            self.body.append('<a href="#%s">' % node['refid'])
            self.context.append('</a>')
        else:
            self.context.append('')
        self.body.append(self.starttag(node, 'span', '', CLASS='problematic'))

    def depart_problematic(self, node):
        self.body.append('</span>')
        self.body.append(self.context.pop())

    def visit_raw(self, node):
        if 'html' in node.get('format', '').split():
            t = isinstance(node.parent, nodes.TextElement) and 'span' or 'div'
            if node['classes']:
                self.body.append(self.starttag(node, t, suffix=''))
            self.body.append(node.astext())
            if node['classes']:
                self.body.append('</%s>' % t)
        # Keep non-HTML raw text out of output:
        raise nodes.SkipNode

    def visit_reference(self, node):
        atts = {'class': 'reference'}
        if 'refuri' in node:
            atts['href'] = node['refuri']
            if ( self.settings.cloak_email_addresses
                 and atts['href'].startswith('mailto:')):
                atts['href'] = self.cloak_mailto(atts['href'])
                self.in_mailto = True
            atts['class'] += ' external'
        else:
            assert 'refid' in node, \
                   'References must have "refuri" or "refid" attribute.'
            atts['href'] = '#' + node['refid']
            atts['class'] += ' internal'
        if (len(node) == 1 and (isinstance(node[0], nodes.image) and
                                not isinstance(node.parent, nodes.figure))):
            node0 = node[0]
            halign = ''
            if 'align' in node0:
                for alignval in [x.strip() for x in node0['align'].split(',')]:
                    if alignval in ('left', 'right', 'center'):
                        halign = alignval
            if halign == 'center':
                self.body.append(
                    '<div style="height:auto;margin:16px auto;display:table">' +
                    '\n')
                self.context.append('</a></div>')
            elif halign in ('left', 'right'):
                self.body.append(
                    '<div class="align-%s" style="height:auto">\n' % halign)
                self.context.append('</a></div>')
            elif not isinstance(node.parent, nodes.TextElement):
                self.body.append(
                    '<div style="height:auto">\n')
                self.context.append('</a></div>')
            else:
                self.context.append('</a>')

            atts['class'] += ' image-reference'
            atts['style'] = 'display:inline-block'
        else:
            self.context.append('</a>')
        self.body.append(self.starttag(node, 'a', '', **atts))

    def depart_reference(self, node):
        self.body.append(self.context.pop())
        if not isinstance(node.parent, nodes.TextElement):
            self.body.append('\n')
        self.in_mailto = False

    def visit_revision(self, node):
        self.visit_docinfo_item(node, 'revision', meta=False)

    def depart_revision(self, node):
        self.depart_docinfo_item()

    def visit_row(self, node):
        self.body.append(self.starttag(node, 'tr', ''))
        node.column = 0

    def depart_row(self, node):
        self.body.append('</tr>\n')

    def visit_rubric(self, node):
        self.body.append(self.starttag(node, 'p', '', CLASS='rubric'))

    def depart_rubric(self, node):
        self.body.append('</p>\n')

    def visit_section(self, node):
        self.section_level += 1
        self.body.append(
            self.starttag(node, 'section', ''))

    def depart_section(self, node):
        self.section_level -= 1
        self.body.append('</section>\n')

    def visit_sidebar(self, node):
        self.body.append(
            self.starttag(node, 'div', CLASS='sidebar'))
        self.in_sidebar = True

    def depart_sidebar(self, node):
        self.body.append('</div>\n')
        self.in_sidebar = False

    def visit_status(self, node):
        self.visit_docinfo_item(node, 'status', meta=False)

    def depart_status(self, node):
        self.depart_docinfo_item()

    def visit_strong(self, node):
        self.body.append(self.starttag(node, 'strong', ''))

    def depart_strong(self, node):
        self.body.append('</strong>')

    def visit_subscript(self, node):
        self.body.append(self.starttag(node, 'sub', ''))

    def depart_subscript(self, node):
        self.body.append('</sub>')

    def visit_substitution_definition(self, node):
        """Internal only."""
        raise nodes.SkipNode

    def visit_substitution_reference(self, node):
        self.unimplemented_visit(node)

    # h1–h6 elements must not be used to markup subheadings, subtitles,
    # alternative titles and taglines unless intended to be the heading for a
    # new section or subsection.
    # -- http://www.w3.org/TR/html/sections.html#headings-and-sections

    def visit_subtitle(self, node):
        if isinstance(node.parent, nodes.sidebar):
            classes = 'sidebar-subtitle'
        elif isinstance(node.parent, nodes.document):
            classes = 'subtitle'
            self.in_document_title = len(self.body)
        elif isinstance(node.parent, nodes.section):
            classes = 'section-subtitle'
        self.body.append(self.starttag(node, 'p', '', CLASS=classes))

    def depart_subtitle(self, node):
        self.body.append('</p>\n')
        if self.in_document_title:
            self.subtitle = self.body[self.in_document_title:-1]
            self.in_document_title = 0
            self.body_pre_docinfo.extend(self.body)
            self.html_subtitle.extend(self.body)
            del self.body[:]

    def visit_superscript(self, node):
        self.body.append(self.starttag(node, 'sup', ''))

    def depart_superscript(self, node):
        self.body.append('</sup>')

    def visit_system_message(self, node):
        self.body.append(self.starttag(node, 'div', CLASS='system-message'))
        self.body.append('<p class="system-message-title">')
        backref_text = ''
        if len(node['backrefs']):
            backrefs = node['backrefs']
            if len(backrefs) == 1:
                backref_text = ('; <em><a href="#%s">backlink</a></em>'
                                % backrefs[0])
            else:
                i = 1
                backlinks = []
                for backref in backrefs:
                    backlinks.append('<a href="#%s">%s</a>' % (backref, i))
                    i += 1
                backref_text = ('; <em>backlinks: %s</em>'
                                % ', '.join(backlinks))
        if node.hasattr('line'):
            line = ', line %s' % node['line']
        else:
            line = ''
        self.body.append('System Message: %s/%s '
                         '(<span class="docutils literal">%s</span>%s)%s</p>\n'
                         % (node['type'], node['level'],
                            self.encode(node['source']), line, backref_text))

    def depart_system_message(self, node):
        self.body.append('</div>\n')

    # tables
    # ------
    # no hard-coded border setting in the table head::

    def visit_table(self, node):
        classes = [cls.strip(u' \t\n')
                   for cls in self.settings.table_style.split(',')]
        tag = self.starttag(node, 'table', CLASS=' '.join(classes))
        self.body.append(tag)

    def depart_table(self, node):
        self.body.append('</table>\n')

    def visit_target(self, node):
        if not ('refuri' in node or 'refid' in node
                or 'refname' in node):
            self.body.append(self.starttag(node, 'span', '', CLASS='target'))
            self.context.append('</span>')
        else:
            self.context.append('')

    def depart_target(self, node):
        self.body.append(self.context.pop())

    # no hard-coded vertical alignment in table body::

    def visit_tbody(self, node):
        self.write_colspecs()
        self.body.append(self.context.pop()) # '</colgroup>\n' or ''
        self.body.append(self.starttag(node, 'tbody'))

    def depart_tbody(self, node):
        self.body.append('</tbody>\n')

    def visit_term(self, node):
        self.body.append(self.starttag(node, 'dt', ''))

    def depart_term(self, node):
        """
        Leave the end tag to `self.visit_definition()`, in case there's a
        classifier.
        """
        pass

    def visit_tgroup(self, node):
        # Mozilla needs <colgroup>:
        self.body.append(self.starttag(node, 'colgroup'))
        # Appended by thead or tbody:
        self.context.append('</colgroup>\n')
        node.stubs = []

    def depart_tgroup(self, node):
        pass

    def visit_thead(self, node):
        self.write_colspecs()
        self.body.append(self.context.pop()) # '</colgroup>\n'
        # There may or may not be a <thead>; this is for <tbody> to use:
        self.context.append('')
        self.body.append(self.starttag(node, 'thead'))

    def depart_thead(self, node):
        self.body.append('</thead>\n')

    def visit_title(self, node):
        """Only 6 section levels are supported by HTML."""
        check_id = 0  # TODO: is this a bool (False) or a counter?
        close_tag = '</p>\n'
        if isinstance(node.parent, nodes.topic):
            self.body.append(
                  self.starttag(node, 'p', '', CLASS='topic-title first'))
        elif isinstance(node.parent, nodes.sidebar):
            self.body.append(
                  self.starttag(node, 'p', '', CLASS='sidebar-title'))
        elif isinstance(node.parent, nodes.Admonition):
            self.body.append(
                  self.starttag(node, 'p', '', CLASS='admonition-title'))
        elif isinstance(node.parent, nodes.table):
            self.body.append(
                  self.starttag(node, 'caption', ''))
            close_tag = '</caption>\n'
        elif isinstance(node.parent, nodes.document):
            self.body.append(self.starttag(node, 'h1', '', CLASS='title'))
            close_tag = '</h1>\n'
            self.in_document_title = len(self.body)
        else:
            assert isinstance(node.parent, nodes.section)
            h_level = self.section_level + self.initial_header_level - 1
            atts = {}
            if (len(node.parent) >= 2 and
                isinstance(node.parent[1], nodes.subtitle)):
                atts['CLASS'] = 'with-subtitle'
            self.body.append(
                  self.starttag(node, 'h%s' % h_level, '', **atts))
            atts = {}
            if node.hasattr('refid'):
                atts['class'] = 'toc-backref'
                atts['href'] = '#' + node['refid']
            if atts:
                self.body.append(self.starttag({}, 'a', '', **atts))
                close_tag = '</a></h%s>\n' % (h_level)
            else:
                close_tag = '</h%s>\n' % (h_level)
        self.context.append(close_tag)

    def depart_title(self, node):
        self.body.append(self.context.pop())
        if self.in_document_title:
            self.title = self.body[self.in_document_title:-1]
            self.in_document_title = 0
            self.body_pre_docinfo.extend(self.body)
            self.html_title.extend(self.body)
            del self.body[:]

    def visit_title_reference(self, node):
        self.body.append(self.starttag(node, 'cite', ''))

    def depart_title_reference(self, node):
        self.body.append('</cite>')

    def visit_topic(self, node):
        self.body.append(self.starttag(node, 'div', CLASS='topic'))
        self.topic_classes = node['classes']
        # TODO: replace with ::
        #   self.in_contents = 'contents' in node['classes']

    def depart_topic(self, node):
        self.body.append('</div>\n')
        self.topic_classes = []
        # TODO self.in_contents = False

    def visit_transition(self, node):
        self.body.append(self.emptytag(node, 'hr', CLASS='docutils'))

    def depart_transition(self, node):
        pass

    def visit_version(self, node):
        self.visit_docinfo_item(node, 'version', meta=False)

    def depart_version(self, node):
        self.depart_docinfo_item()

    def unimplemented_visit(self, node):
        raise NotImplementedError('visiting unimplemented node type: %s'
                                  % node.__class__.__name__)


class SimpleListChecker(nodes.GenericNodeVisitor):

    """
    Raise `nodes.NodeFound` if non-simple list item is encountered.

    Here "simple" means a list item containing nothing other than a single
    paragraph, a simple list, or a paragraph followed by a simple list.

    This version also checks for simple field lists and docinfo.
    """

    def default_visit(self, node):
        raise nodes.NodeFound

    def visit_list_item(self, node):
        children = [child for child in node.children
                    if not isinstance(child, nodes.Invisible)]
        if (children and isinstance(children[0], nodes.paragraph)
            and (isinstance(children[-1], nodes.bullet_list) or
                 isinstance(children[-1], nodes.enumerated_list) or
                 isinstance(children[-1], nodes.field_list))):
            children.pop()
        if len(children) <= 1:
            return
        else:
            raise nodes.NodeFound

    def pass_node(self, node):
        pass

    def ignore_node(self, node):
        # ignore nodes that are never complex (can contain only inline nodes)
        raise nodes.SkipNode

    # Paragraphs and text
    visit_Text = ignore_node
    visit_paragraph = ignore_node

    # Lists
    visit_bullet_list = pass_node
    visit_enumerated_list = pass_node
    visit_docinfo = pass_node

    # Docinfo nodes:
    visit_author = ignore_node
    visit_authors = visit_list_item
    visit_address = visit_list_item
    visit_contact = pass_node
    visit_copyright = ignore_node
    visit_date = ignore_node
    visit_organization = ignore_node
    visit_status = ignore_node
    visit_version = visit_list_item

    # Definition list:
    visit_definition_list = pass_node
    visit_definition_list_item = pass_node
    visit_term = ignore_node
    visit_classifier = pass_node
    visit_definition = visit_list_item

    # Field list:
    visit_field_list = pass_node
    visit_field = pass_node
    # the field body corresponds to a list item
    visit_field_body = visit_list_item
    visit_field_name = ignore_node

    # Invisible nodes should be ignored.
    visit_comment = ignore_node
    visit_substitution_definition = ignore_node
    visit_target = ignore_node
    visit_pending = ignore_node
