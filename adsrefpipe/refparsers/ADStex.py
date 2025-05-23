
import sys, os
import argparse
from typing import List, Dict

from adsputils import setup_logging, load_config
logger = setup_logging('refparsers')
config = {}
config.update(load_config())

from adsrefpipe.refparsers.toREFs import TEXtoREFs
from adsrefpipe.refparsers.reference import LatexReference


class ADStexToREFs(TEXtoREFs):
    """
    This class processes ADS TEX references and converts them into a standardized reference format.
    It handles the removal of LaTeX code and performs reference cleaning.
    """

    # some references have latex code, remove them
    latex_reference = LatexReference("")

    def __init__(self, filename: str, buffer: str):
        """
        initialize the parser for ADStexToREFs

        :param filename: path to the reference file
        :param buffer: buffer containing the references
        """
        TEXtoREFs.__init__(self, filename, buffer, ADStexToREFs)


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
                reference = self.latex_reference.cleanup(reference)
                logger.debug("confTEX: parsing %s" % reference)
                parsed_references.append(self.merge({'refstr': reference, 'refraw': reference}, self.any_item_num(item_nums, i)))

            references.append({'bibcode': bibcode, 'references': parsed_references})
            logger.debug("%s: parsed %d references" % (bibcode, len(references)))

        return references


def toREFs(filename: str, buffer: str):      # pragma: no cover
    """
    this is a local function, called from main, for testing purposes

    :param filename:
    :param buffer:
    :return:
    """
    results = ADStexToREFs(filename=filename, buffer=buffer).process_and_dispatch()
    for result in results:
        print(result['bibcode'])
        for reference in result['references']:
            print(reference['refstr'])
        print()



# This is the main program used for manual testing and verification of LaTeX references.
# It allows parsing references from either a file or a buffer, and if no input is provided,
# it runs a source test file to verify the functionality against expected parsed results.
# The test results are printed to indicate whether the parsing is successful or not.
if __name__ == '__main__':      # pragma: no cover
    parser = argparse.ArgumentParser(description='Parse latex references')
    parser.add_argument('-f', '--filename', help='the path to source file')
    parser.add_argument('-b', '--buffer', help='latex reference(s)')
    args = parser.parse_args()
    if args.filename:
        toREFs(args.filename, buffer=None)
    elif args.buffer:
        toREFs(filename=None, buffer=args.buffer)
    # if no reference source is provided, just run the source test file
    elif not args.filename and not args.buffer:
        filename = os.path.abspath(os.path.dirname(__file__) + '/../tests/unittests/stubdata/tex/ADS/0/iss0.tex')
        compare = ''
        for i,one in enumerate(ADStexToREFs(filename=filename, buffer=None).process_and_dispatch()):
            compare += '---<%s>---\n'%one['bibcode']
            for ref in one['references']:
                compare += '%s\n'%ref['refstr'].strip()
        with open(os.path.abspath(filename + '.result'), 'r', encoding='utf-8', errors='ignore') as f:
            from_file = f.read()
            if from_file == compare.strip():
                print('Test `%s` passed!' % filename)
            else:
                print('Test `%s` failed!' % filename)
    sys.exit(0)
