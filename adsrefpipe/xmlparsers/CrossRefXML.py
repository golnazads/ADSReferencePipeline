import sys, os
import re
import argparse

from adsputils import setup_logging, load_config
logger = setup_logging('reference-xml')
config = {}
config.update(load_config())

from adsrefpipe.xmlparsers.reference import XMLreference, ReferenceError
from adsrefpipe.xmlparsers.common import get_references, get_xml_block, format_authors, extract_tag, match_int, \
    match_arxiv_id


class CrossRefreference(XMLreference):

    re_journal_a_and_a = re.compile(r'(AA|A& A|A &A)', re.IGNORECASE)
    re_author = (re.compile(r'([A-Z]{1,3})(\ .*)'), r'\1.\2')
    re_unstructured = [
        (re.compile(r'</?i>'), ''),
        (re.compile(r'</?b>'), ''),
    ]

    def parse(self, prev_ref=None):
        """
        tags that CrossRef supprts (source per Edwin: https://www.crossref.org/education/metadata-stewardship/maintaining-your-metadata/adding-metadata-to-an-existing-record/#00177)
        ['article_title', 'doi', 'isbn', 'unstructured_citation', 'author', 'series_title', 'journal_title',
         'edition_number', 'cYear', 'volume', 'first_page', 'volume_title', 'issue', 'issn', 'isbn', 'edition_number',
         'std_designator', 'standards_body_name', 'standards_body_acronym', 'component_number']

        :param prev_ref: 
        :return: 
        """
        self.parsed = 0

        self['year'] = match_int(self.xmlnode_nodecontents('cYear'))
        self['volume'] = match_int(self.xmlnode_nodecontents('volume'))
        self['issue'] = self.xmlnode_nodecontents('issue')
        self['pages'] = self.xmlnode_nodecontents('first_page')
        try:
            if self['pages'][-1] in map(chr, range(65, 91)):
                self['pages'] = "%s%s" % (self['pages'][-1], self['pages'][:-1])
        except:
            pass
        self['page'], self['qualifier'] = self.parse_pages(self['pages'].replace(',', ''))
        self['pages'] = self.combine_page_qualifier(self['page'], self['qualifier'])

        journal = self.get_journal()
        if journal:
            self['jrlstr'] = journal
            if journal == 'Journal of Cosmology and Astroparticle Physics':
                self['issue'] = "0" * (2 - len(self['issue'])) + self['issue']
                self['jrlstr'] += " JCAP%s(%s)%s" % (self['issue'], self['year'], self['pages'])
                self['jrlstr'] = journal
        title = self.get_title()
        if title:
            self['ttlstr'] = title

        self['issn'] = self.xmlnode_nodecontents('issn')
        self['doi'] = self.xmlnode_nodecontents('doi')

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
            self['authors'] = ', '.join(map(format_authors, authors))
        else:
            self['authors'] = ''

        self['unstructured'] = self.xmlnode_nodecontents('unstructured_citation').strip()
        for one_set in self.re_unstructured:
            self['unstructured'] = one_set[0].sub(one_set[1], self['unstructured'])

        if len(self['unstructured']) > 0:
            self['refplaintext'] = self['refstr'] = self['unstructured']
        else:
            try:
                # try to come up with a decent plainstring if all
                # the default fields were parsed ok
                self['refstr'] = ', '.join([self['authors'], self['year'], self['jrlstr'], self['volume'], self['pages']])
            except KeyError:
                self['doi'] = self['doi'].strip()
                if len(self['doi']) > 0:
                    self['refstr'] = 'doi:' + self['doi']
                else:
                    self['refstr'] = self.get_reference_str()

        eprint = match_arxiv_id(str(self.reference_str))
        if eprint:
            self['eprint'] = eprint

        self.parsed = 1

    def get_reference_str(self):
        """
        # plaintext reference, as given in the XML reference

        :return: 
        """
        return self.strip_tags(str(self.reference_str), change=' ')

    def get_journal(self):
        """
        both journal_title and series_title tags are assigned to journal variable

        :return:
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

    def get_title(self):
        """
        both article_title and volume_title tags are assigned to title variable

        :return:
        """
        for title in ['article_title', 'volume_title']:
            title_str = self.xmlnode_nodecontents(title)
            if title_str:
                return title_str
        return None


re_skip = re.compile(r'''<citation\ key=".*?"\ />\s*</citation_list>''', re.DOTALL | re.VERBOSE)
re_linefeed = re.compile(r'\n')
re_ref_issue = re.compile(r'<ref_issue>.*?</ref_issue>')

def CrossReftoREFs(filename=None, buffer=None, unicode=None):
    """
    
    :param filename: 
    :param unicode: 
    :return: 
    """
    references = []
    pairs = get_references(filename=filename, buffer=buffer)

    for pair in pairs:
        bibcode = pair[0]
        buffer = pair[1]
        block_references = get_xml_block(buffer, 'citation')
        for reference in block_references:
            if re_skip.search(re_linefeed.sub('', reference)):
                continue
            reference = re_ref_issue.sub('', reference)

            logger.debug("CrossRefxml: parsing %s" % reference)
            try:
                crossref_reference = CrossRefreference(reference)
                references.append(crossref_reference.get_parsed_reference())
            except ReferenceError as error_desc:
                logger.error("CrossRefxml: error parsing reference: %s" %error_desc)
                continue

            logger.debug("%s: parsed %d references" % (bibcode, len(references)))

    return references


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parse CrossRef references')
    parser.add_argument('-f', '--filename', help='the path to source file')
    parser.add_argument('-b', '--buffer', help='xml reference(s)')
    args = parser.parse_args()
    if args.filename:
        print(CrossReftoREFs(filename=args.filename))
    if args.buffer:
        print(CrossReftoREFs(buffer=args.buffer))
    # if no reference source is provided, just run the source test file
    if not args.filename and not args.buffer:
        print(CrossReftoREFs(os.path.abspath(os.path.dirname(__file__) + '/../tests/unittests/stubdata/test.ref.xml')))
    sys.exit(0)
    # /proj/ads/references/sources/PLoSO/0007/10.1371_journal.pone.0048146.xref.xml