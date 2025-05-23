
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


class CrossRefreference(XMLreference):
    """
    This class handles parsing CrossRef references in XML format. It extracts citation information such as authors,
    year, journal, title, volume, pages, DOI, and eprint, and stores the parsed details.
    """

    # to match journal names with variations of "A & A" or "AA" (case-insensitive)
    re_journal_a_and_a = re.compile(r'(AA|A& A|A &A)', re.IGNORECASE)
    # to match author initials and format them correctly (e.g., "A B" -> "A. B.")
    re_author = (re.compile(r'([A-Z]{1,3})(\ .*)'), r'\1.\2')
    # to remove <i> and <b> HTML tags from unstructured text
    re_unstructured = [
        (re.compile(r'</?i>'), ''),
        (re.compile(r'</?b>'), ''),
    ]
    # to match first initials
    re_first_initial = re.compile(r'\b\w\.')
    # to match "et al." or "et al" (case-sensitive)
    re_etal = re.compile(r'\bet\s+al\.?')

    def parse(self):
        """
        parse the WILEY reference and extract citation information such as authors, year, title, and DOI

        tags that CrossRef supprts (source per Edwin: https://www.crossref.org/education/metadata-stewardship/maintaining-your-metadata/adding-metadata-to-an-existing-record/#00177)
        ['article_title', 'doi', 'isbn', 'unstructured_citation', 'author', 'series_title', 'journal_title',
         'edition_number', 'cYear', 'volume', 'first_page', 'volume_title', 'issue', 'issn', 'isbn', 'edition_number',
         'std_designator', 'standards_body_name', 'standards_body_acronym', 'component_number']

        :return:
        """
        self.parsed = 0

        refstr = self.dexml(self.reference_str.toxml())

        authors = self.parse_authors()
        year = self.match_int(self.xmlnode_nodecontents('cYear'))
        if not year:
            year = self.match_year(refstr)

        volume = self.match_int(self.xmlnode_nodecontents('volume'))
        issue = self.xmlnode_nodecontents('issue')
        issn = self.xmlnode_nodecontents('issn')

        page = self.xmlnode_nodecontents('first_page')
        try:
            if page[-1] in map(chr, range(65, 91)):
                page = "%s%s" % (page[-1], page[:-1])
        except:
            pass

        self['authors'] = authors
        self['year'] = year

        self['volume'] = volume

        # not using these two, but keep them for possible future use
        self['issue'] = issue
        self['issn'] = issn

        self['page'], self['qualifier'] = self.parse_pages(page.replace(',', ''))
        self['pages'] = self.combine_page_qualifier(self['page'], self['qualifier'])

        journal = self.parse_journal()
        if journal:
            self['jrlstr'] = journal
            if journal == 'Journal of Cosmology and Astroparticle Physics':
                self['issue'] = "0" * (2 - len(self['issue'])) + self['issue']
                self['jrlstr'] += " JCAP%s(%s)%s" % (self['issue'], self['year'], self['pages'])
                self['jrlstr'] = journal
        title = self.parse_title()
        if title:
            self['ttlstr'] = title

        doi = self.xmlnode_nodecontents('doi')
        if not doi:
            doi = self.match_doi(refstr)
        eprint = self.match_arxiv_id(refstr)

        if doi:
            self['doi'] = doi
        if eprint:
            self['eprint'] = eprint

        self['refstr'] = self.get_reference_str()
        if not self['refstr']:
            self['refplaintext'] = self.xmlnode_nodecontents('unstructured_citation').strip()
            for one_set in self.re_unstructured:
                self['refplaintext'] = one_set[0].sub(one_set[1], self['refplaintext'])
            if not self['refplaintext']:
                self['refplaintext'] = self.get_reference_plain_text(self.to_ascii(refstr))

        self.parsed = 1

    def format_authors(self, ref_str: str, input_separator: List[str] = [], input_space: List[str] = []) -> str:
        """
        format the authors from a given reference string by processing the input separators and spaces

        a utility function to format author names commonly found in references. reformats strings like "F. Last, ..."
        into "Last, F."; for example:
            I. Affleck, A. W. W. Ludwig, H.-B. Pang and D. L. Cox
        is formatted into:
            Affleck I., Ludwig A. W. W., Pang H.-B., Cox D. L.
        also handles "et al." properly and leaves author strings already in "Last F." format untouched

        :param ref_str: the reference string containing author information to be formatted
        :param input_separator: a list of separators used to split author names (default is an empty list)
        :param input_space: a list of space characters that may be used for splitting author names (default is an empty list)
        :return: a formatted string of authors with appropriate separators and spaces
        """
        separator = input_separator if input_separator != [] else [',', r'\band\b', '&']
        space = input_space if input_space != [] else [' ']

        re_separator = re.compile(r'\s*(?:' + '|'.join(separator) + r')\s*')
        re_space = re.compile(r'\s*(?:' + '|'.join(space) + r')\s*')

        formatted = []
        etal = ''
        match = self.re_etal.search(ref_str)
        if match:
            etal = ref_str[match.start():match.end()]
            ref_str = ref_str[:match.start()] + ref_str[match.end():]

        authors = re_separator.split(ref_str)

        for a in authors:
            parts = re_space.split(a)
            if parts == []:
                continue
            first = ''
            while len(parts) > 1 and self.re_first_initial.match(parts[0]):
                first = first + ' ' + parts.pop(0)
            ref_str = ' '.join(parts) + first
            formatted.append(ref_str)

        if etal:
            formatted.append(etal)

        return ', '.join(formatted)

    def parse_authors(self) -> str:
        """
        parse the authors from the reference string and format them accordingly

        :return: a formatted string of authors
        """
        authors = self.xmlnode_nodescontents('author')
        new_authors = []
        for author in authors:
            name_parts = author.split()
            # usually there is only the first author, so if it can be split up to two parts, we are all set
            # also make sure first initial is capital, and last name is capitalized
            if len(name_parts) == 2:
                new_author = ''
                for init in name_parts[0]:
                    if init.isalpha():
                        new_author += init.upper() + '. '
                new_author += name_parts[1][0].upper() + name_parts[1][1:]
                new_authors.append(new_author)
            # only last name, make sure it is capitalized
            elif len(name_parts) == 1:
                new_authors.append(name_parts[0][0].upper() + name_parts[0][1:])
            else:
                new_authors.append(self.re_author[0].sub(self.re_author[1], author))
        if len(new_authors) > 0:
            return ', '.join(map(self.format_authors, authors))
        return ''

    def parse_journal(self) -> str:
        """
        parse journal from the reference string

        both journal_title and series_title tags are assigned to journal variable

        :return: the journal if found, otherwise None
        """
        journal = self.xmlnode_nodecontents('journal_title')
        if journal:
            journal = self.re_journal_a_and_a.sub('A&A', journal)
            # 8/27/2020 was not able to find this case, but keeping it anyway
            if journal == 'NAT':
                journal = 'Natur'
            return journal
        journal = self.xmlnode_nodecontents('series_title')
        if journal:
            return journal
        return None

    def parse_title(self) -> str:
        """
        parse the title from the reference string

        both article_title and volume_title tags are assigned to title variable

        :return: the title if found, otherwise None
        """
        for title in ['article_title', 'volume_title']:
            title_str = self.xmlnode_nodecontents(title)
            if title_str:
                return title_str
        return None


class CrossRefToREFs(XMLtoREFs):
    """
    This class converts CrossRef XML references to a standardized reference format. It processes raw CrossRef references from
    either a file or a buffer and outputs parsed references, including bibcodes, authors, volume, pages, and DOI.
    """

    # to clean up references by replacing certain patterns
    reference_cleanup = [
        (re.compile(r'<ref_issue>.*?</ref_issue>'), ''),
    ]

    # to match and skip citation tags with a specific key followed by closing citation list tag
    re_skip = re.compile(r'<citation\ key=".*?"\ />\s*</citation_list>', re.DOTALL | re.VERBOSE)
    # to match line feed characters
    re_linefeed = re.compile(r'\n')

    def __init__(self, filename: str, buffer: str):
        """
        initialize the CrossReftoREFs object to process CrossRef references

        :param filename: the path to the source file
        :param buffer: the XML references as a buffer
        """
        XMLtoREFs.__init__(self, filename, buffer, parsername=CrossRefToREFs, tag='citation')

    def cleanup(self, reference: str) -> str:
        """
        clean up the reference string by replacing specific patterns

        :param reference: the raw reference string to clean
        :return: cleaned reference string
        """
        for (compiled_re, replace_str) in self.reference_cleanup:
            reference = compiled_re.sub(replace_str, reference)
        return reference

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
            for i, raw_reference in enumerate(block_references):
                if self.re_skip.search(self.re_linefeed.sub('', raw_reference)):
                    continue
                reference = self.cleanup(raw_reference)

                logger.debug("CrossRefxml: parsing %s" % reference)
                try:
                    crossref_reference = CrossRefreference(reference)
                    parsed_references.append(self.merge({**crossref_reference.get_parsed_reference(), 'refraw': raw_reference}, self.any_item_num(item_nums, i)))
                except ReferenceError as error_desc:
                    logger.error("CrossRefxml: error parsing reference: %s" % error_desc)

            references.append({'bibcode': bibcode, 'references': parsed_references})
            logger.debug("%s: parsed %d references" % (bibcode, len(references)))

        return references


# This is the main program used for manual testing and verification of CrossRefXML references.
# It allows parsing references from either a file or a buffer, and if no input is provided,
# it runs a source test file to verify the functionality against expected parsed results.
# The test results are printed to indicate whether the parsing is successful or not.
from adsrefpipe.tests.unittests.stubdata import parsed_references
if __name__ == '__main__':      # pragma: no cover
    parser = argparse.ArgumentParser(description='Parse CrossRef references')
    parser.add_argument('-f', '--filename', help='the path to source file')
    parser.add_argument('-b', '--buffer', help='xml reference(s)')
    args = parser.parse_args()
    if args.filename:
        print(CrossRefToREFs(filename=args.filename).process_and_dispatch())
    elif args.buffer:
        print(CrossRefToREFs(buffer=args.buffer).process_and_dispatch())
    # if no reference source is provided, just run the source test file
    elif not args.filename and not args.buffer:
        filename = os.path.abspath(os.path.dirname(__file__) + '/../tests/unittests/stubdata/test.xref.xml')
        result = CrossRefToREFs(filename=filename, buffer=None).process_and_dispatch()
        if result == parsed_references.parsed_crossref:
            print('Test passed!')
        else:
            print('Test failed!')
    sys.exit(0)
