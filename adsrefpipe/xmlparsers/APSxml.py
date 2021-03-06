import sys, os
import re
import argparse

from adsputils import setup_logging, load_config

logger = setup_logging('reference-xml')
config = {}
config.update(load_config())

from adsrefpipe.xmlparsers.reference import XMLreference, ReferenceError
from adsrefpipe.xmlparsers.common import get_references, get_xml_block, extract_tag, match_arxiv_id


class APSreference(XMLreference):

    re_first = re.compile(r'\w\.$')

    def parse(self, prevref=None):
        """

        :param prevref:
        :return:
        """

        self.parsed = 0

        authors = self.xmlnode_nodescontents('refauth')
        date = self.xmlnode_nodecontents('date')
        volume = self.xmlnode_nodecontents('volume')
        pages = self.xmlnode_nodecontents('pages')
        issue = self.xmlnode_nodecontents('issue')
        journal = self.xmlnode_nodecontents('jtitle') or self.xmlnode_nodecontents('journal')
        eprint = match_arxiv_id(self.xmlnode_nodecontents('eprintid'))
        issn = self.xmlnode_nodecontents('issn')
        doi = self.xmlnode_nodecontents('doi')

        # we have seen some url-encoded DOIs in APS input, so try this
        # (which is a no-op for non-encoded input)
        doi = self.url_decode(doi)

        self['jrlstr'] = journal
        self['authors'] = ', '.join(map(self.parse_authors, authors))
        if date and len(date) >= 4:
            self['year'] = date[0:4]
        self['volume'] = self.parse_volume(volume)
        self['page'], self['qualifier'] = self.parse_pages(pages)
        self['pages'] = self.combine_page_qualifier(self['page'], self['qualifier'])
        if issue:
            self['issue'] = issue

        if eprint:
            self['eprint'] = eprint
        if issn:
            self['issn'] = issn
        if doi:
            self['doi'] = doi

        # try to come up with a decent plainstring if all
        # the default fields were parsed ok
        self['refstr'] = ' '.join([self['authors'], date, journal, volume, pages])

        self.parsed = 1

    def parse_authors(self, authors):
        """

        :param authors:
        :return:
        """
        authors = authors.strip()
        if not authors: return ''

        authors = self.unicode.u2asc(authors)

        # see if this is an author string already in its canonical form
        # "Authlast1 F., Authlast2, F...."
        if ',' in authors:
            return authors

        # or if it's just a last name or abbreviation
        parts = authors.split(' ')
        if len(parts) <= 1:
            return authors

        # otherwise parse it and recompose it as "Last F."
        first = parts.pop(0)
        while len(parts) > 1 and self.re_first.match(parts[0]):
            first = first + ' ' + parts.pop(0)
        authors = ' '.join(parts) + ' ' + first

        return authors

re_closing_tag = re.compile(r'</references>\s*$')
re_formula = re.compile(r'<formula.*?>.*?</formula>')
re_previous_tag = re.compile(r'<prevau>')
re_previous_ref = re.compile(r'<ibid>')

def APStoREFs(filename=None, buffer=None, unicode=None):
    """

    :param filename:
    :param buffer:
    :param unicode:
    :return:
    """
    references = []
    pairs = get_references(filename=filename, buffer=buffer)

    for pair in pairs:
        bibcode = pair[0]
        buffer = pair[1]
        block_references = get_xml_block(buffer, '(ref|citation)')

        # remove closing '</reference>' tag at end of file
        if block_references and len(block_references):
            block_references[-1] = re_closing_tag.sub('', block_references[-1])

        prev_reference = ''
        for reference in block_references:
            reference = re_formula.sub('', reference)

            logger.debug("APSXML: parsing %s" % reference)

            # take care of previous author tag
            reference = re_previous_tag.sub('---',reference)
            if prev_reference:
                reference = re_previous_ref.sub(prev_reference,reference)
            reference,prev_reference = extract_tag(reference,'journal',remove=0,keeptag=1)

            try:
                aps_reference = APSreference(reference)
                references.append(aps_reference.get_parsed_reference())
            except ReferenceError as error_desc:
                logger.error("APSxml: error parsing reference: %s" %error_desc)
                continue

        logger.debug("%s: parsed %d references" % (bibcode, len(references)))

    return references


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parse APS references')
    parser.add_argument('-f', '--filename', help='the path to source file')
    parser.add_argument('-b', '--buffer', help='xml reference(s)')
    args = parser.parse_args()
    if args.filename:
        print(APStoREFs(filename=args.filename))
    if args.buffer:
        print(APStoREFs(buffer=args.buffer))
    # if no reference source is provided, just run the source test file
    if not args.filename and not args.buffer:
        print(APStoREFs(os.path.abspath(os.path.dirname(__file__) + '/../tests/unittests/stubdata/test.aps.xml')))
    sys.exit(0)
    # two formats
    # /proj/ads/references/sources/PhRvB/0081/2010PhRvB..81r4520P.ref.xml
    # /proj/ads/references/sources/PhRvA/0001/1970PhRvA...1..995L.ref.xml
