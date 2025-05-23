
import sys, os
import regex as re
import argparse
from typing import List, Dict

from adsputils import setup_logging, load_config
logger = setup_logging('refparsers')
config = {}
config.update(load_config())

from adsrefpipe.refparsers.reference import XMLreference, ReferenceError
from adsrefpipe.refparsers.toREFs import XMLtoREFs
from adsrefpipe.refparsers.unicode import tostr


class RSCreference(XMLreference):
    """
    This class handles parsing RSC references in XML format. It extracts citation information such as authors,
    year, journal, title, volume, pages, DOI, and eprint, and stores the parsed details.
    """

    # to match multiple consecutive spaces
    re_match_spaces = re.compile(r'\s\s+')
    # to match various forms of "thesis" or "dissertation" (case-insensitive)
    re_match_thesis = re.compile(r'(MS thesis|PhD Thesis|PhD|Ph.D.|Thesis|Dissertation|Doctoral)', re.IGNORECASE)
    # to match first initials
    re_first_initial = re.compile(r'\b\w\.')

    def parse(self):
        """
        parse the RSC reference and extract citation information such as authors, year, title, and DOI

        :return:
        """
        self.parsed = 0

        refstr = self.re_match_spaces.sub(' ', self.xmlnode_nodecontents('citgroup'))

        authors = self.parse_authors()
        year = self.xmlnode_nodecontents('year')

        # <journalcit> tag specifies it is journal
        if len(self.xmlnode_nodecontents('journalcit')) > 0:
            journal = self.xmlnode_nodecontents('title')
            title = ''
        else:
            journal = ''
            title = self.xmlnode_nodecontents('title')

        if not journal and not title:
            journal = ''.join(self.re_match_thesis.findall(refstr))
            if not journal:
                journal = self.xmlnode_nodecontents('arttitle')

        volume = self.xmlnode_nodecontents('volumeno')
        pages = self.xmlnode_nodecontents('fpage')
        issue = self.xmlnode_nodecontents('issue')

        doi = ''
        # for example: <link type="doi">10.1002/9783527635566.ch1</link>
        link = self.xmlnode_textcontents('link', attrs={'type':'doi'})
        if link:
            doi = self.match_doi(link)
        if not doi:
            # attempt to extract doi from refstr
            doi = self.match_doi(refstr)
        eprint = self.match_arxiv_id(refstr)

        # these fields are already formatted the way we expect them
        self['authors'] = authors.strip()
        self['year'] = year.strip()
        self['jrlstr'] = journal.strip()
        self['ttlstr'] = title.strip()

        self['volume'] = self.parse_volume(volume)
        self['page'], self['qualifier'] = self.parse_pages(pages)
        self['pages'] = self.combine_page_qualifier(self['page'], self['qualifier'])
        self['issue'] = issue

        if doi:
            self['doi'] = doi
        if eprint:
            self['eprint'] = f"arXiv:{eprint}"

        self['refstr'] = self.get_reference_str()
        if not self['refstr']:
            self['refplaintext'] = self.get_reference_plain_text(self.to_ascii(refstr))

        self.parsed = 1

    def parse_authors(self) -> str:
        """
        parse the authors from the reference string and format them accordingly

        :return: a formatted string of authors
        """
        author_list = []
        authors = self.xmlnode_nodescontents('citauth', keepxml=1)
        if authors:
            for author in authors:
                author, lastname = self.extract_tag(author, 'surname')
                author, givennames = self.extract_tag(author, 'fname')
                if lastname: an_author = tostr(lastname)
                if an_author and givennames: an_author += ', ' + tostr(givennames)
                if an_author: author_list.append(an_author)
        else:
            authors = self.xmlnode_nodescontents('editor')
            for author in authors:
                # reverse author's first/last names in the form "F. Last1, O. Last2..."
                if self.re_first_initial.match(author):
                    givennames = ' '.join(self.re_first_initial.findall(author))
                    an_author = self.re_match_spaces.sub('', self.re_first_initial.sub('', author)).strip('-').strip()
                    if an_author and givennames: an_author += ', ' + givennames
                    if an_author: author_list.append(an_author)

        return ", ".join(author_list)


class RSCtoREFs(XMLtoREFs):
    """
    This class converts RSC XML references to a standardized reference format. It processes raw RSC references from
    either a file or a buffer and outputs parsed references, including bibcodes, authors, volume, pages, and DOI.
    """

    # to clean up XML blocks by removing certain tags
    block_cleanup = [
        (re.compile(r'</?uri.*?>'), ' href='),
        (re.compile(r'</?SU[BP]>', flags=re.IGNORECASE), ''),   # remove SUB/SUP tags
        (re.compile(r'</?it>', flags=re.IGNORECASE), r''),      # remove italic tag
        (re.compile(r'</?bo>', flags=re.IGNORECASE), r''),      # remove bold tag
    ]

    def __init__(self, filename: str, buffer: str):
        """
        initialize the RSCtoREFs object to process RSC references

        :param filename: the path to the source file
        :param buffer: the XML references as a buffer
        """
        XMLtoREFs.__init__(self, filename, buffer, parsername=RSCtoREFs, tag='citgroup', cleanup=self.block_cleanup)

    def process_and_dispatch(self) -> List[Dict[str, List[Dict[str, str]]]]:
        """
        perform reference cleaning and parsing, then dispatch the parsed references

        :return: a list of dictionaries containing bibcodes and parsed references
        """
        references = []
        for raw_block_references in self.raw_references:
            bibcode = raw_block_references['bibcode']
            block_references = raw_block_references['block_references']
            item_nums = raw_block_references.get('item_nums', [])

            parsed_references = []
            for i, reference in enumerate(block_references):
                logger.debug("RSCxml: parsing %s" % reference)
                try:
                    rsc_reference = RSCreference(reference)
                    parsed_references.append(self.merge({**rsc_reference.get_parsed_reference(), 'refraw': reference}, self.any_item_num(item_nums, i)))
                except ReferenceError as error_desc:
                    logger.error("RSCxml: error parsing reference: %s" % error_desc)

            references.append({'bibcode': bibcode, 'references': parsed_references})
            logger.debug("%s: parsed %d references" % (bibcode, len(references)))

        return references


# This is the main program used for manual testing and verification of RSCxml references.
# It allows parsing references from either a file or a buffer, and if no input is provided,
# it runs a source test file to verify the functionality against expected parsed results.
# The test results are printed to indicate whether the parsing is successful or not.
from adsrefpipe.tests.unittests.stubdata import parsed_references
if __name__ == '__main__':      # pragma: no cover
    parser = argparse.ArgumentParser(description='Parse RSC references')
    parser.add_argument('-f', '--filename', help='the path to source file')
    parser.add_argument('-b', '--buffer', help='xml reference(s)')
    args = parser.parse_args()
    if args.filename:
        print(RSCtoREFs(filename=args.filename, buffer=None).process_and_dispatch())
    elif args.buffer:
        print(RSCtoREFs(buffer=args.buffer, filename=None).process_and_dispatch())
    # if no reference source is provided, just run the source test file
    elif not args.filename and not args.buffer:
        filename = os.path.abspath(os.path.dirname(__file__) + '/../tests/unittests/stubdata/test.rsc.xml')
        result = RSCtoREFs(filename=filename, buffer=None).process_and_dispatch()
        if result == parsed_references.parsed_rsc:
            print('Test passed!')
        else:
            print('Test failed!')
    sys.exit(0)
