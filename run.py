import sys
import os, fnmatch

from adsputils import setup_logging, load_config, get_date
from datetime import timedelta
import time

import argparse

from adsrefpipe import tasks
from adsrefpipe.refparsers.handler import verify
from adsrefpipe.utils import get_date_modified_struct_time, ReprocessQueryType

proj_home = os.path.realpath(os.path.dirname(__file__))
config = load_config(proj_home=proj_home)

app = tasks.app
logger = setup_logging('run.py')


def run_diagnostics(bibcodes: list, source_filenames: list) -> None:
    """
    show diagnostic information based on the provided bibcodes and source filenames

    :param bibcodes: list of bibcodes to retrieve diagnostic data for
    :param source_filenames: list of source filenames to retrieve diagnostic data for
    :return: None
    """
    max_entries_diagnostics = config['MAX_ENTRIES_DIAGNOSTICS']
    # make sure we only send max number of entires per bibcode/source_file to be queried
    if bibcodes:
        bibcodes = bibcodes[:max_entries_diagnostics]
    if source_filenames:
        source_filenames = source_filenames[:max_entries_diagnostics]
    results = app.diagnostic_query(bibcodes, source_filenames)
    for result in results:
        print(result)
    return


def get_source_filenames(source_file_path: str, file_extension: str, date_cutoff: time.struct_time) -> list:
    """
    retrieves a list of files from the given directory with the specified file extension and modified date after the cutoff

    :param source_file_path: the path of the directory to search for files
    :param file_extension: the file extension pattern to match
    :param date_cutoff: the modified date cutoff, files modified after this date will be included only
    :return: list of files in the directory with modified date after the cutoff, if any
    """
    list_files = []
    for root, dirs, files in os.walk(source_file_path):
        for basename in files:
            if fnmatch.fnmatch(basename, file_extension):
                filename = os.path.join(root, basename)
                if get_date_modified_struct_time(filename) >= date_cutoff:
                    list_files.append(filename)
    return list_files


def queue_references(references: list, source_filename: str, source_bibcode: str, parsername: str) -> None:
    """
    queues references for processing by preparing a task and sending it to the queue

    :param references: a list of reference objects to be queued for processing
    :param source_filename: the name of the source file from which references are being queued
    :param source_bibcode: the bibcode associated with the source of the references
    :param parsername: the name of the parser used to extract the references
    :return: None
    """
    resolver_service_url = config['REFERENCE_PIPELINE_SERVICE_URL'] + app.get_reference_service_endpoint(parsername)
    for reference in references:
        reference_task = {'reference': reference,
                          'source_bibcode': source_bibcode,
                          'source_filename': source_filename,
                          'resolver_service_url': resolver_service_url}
        # tasks.task_process_reference.delay(reference_task)
        print('---here')
        tasks.task_process_reference(reference_task)


def process_files(filenames: list) -> None:
    """
    processes the given list of filenames by reading source reference files and sending each reference for processing

    note that there are two ways to queue references: one is to read source files, the other is to query database
    this function handles the former

    :param filenames: list of filenames to be processed
    :return: None
    """
    for filename in filenames:
        # from filename get the parser info
        # file extension, and bibstem and volume directories are used to query database and return the parser info
        # ie for filename `adsrefpipe/tests/unittests/stubdata/txt/ARA+A/0/0000ADSTEST.0.....Z.ref.raw`
        # extension ref.raw, bibstem directory ARA+A and volume directory 0 is used and the
        # parser info is {'name': 'ThreeBibsTxt',
        #                 'extension_pattern': '.ref.raw',
        #                 'reference_service_endpoint': '/text',
        #                 'matches': [[{'journal': 'AnRFM', 'volume_end': 37, 'volume_begin': 34},
        #                              {'journal': 'ARA+A', 'volume_end': 43, 'volume_begin': 40},
        #                              {'journal': 'ARNPS', 'volume_end': 56, 'volume_begin': 52}]]}
        parser_dict = app.get_parser(filename)
        # now map parser name to the class (see adsrefpipe/refparsers/handler.py)
        # ie parser name ThreeBibsTxt is mapped to ThreeBibstemsTXTtoREFs
        # 'ThreeBibsTxt': ThreeBibstemsTXTtoREFs,
        # note that from the class name it is clear which type of parser this is
        # (ie, this is a TXT parser implemented in module adsrefpipe/refparsers/ADStxt.py)
        parser = verify(parser_dict.get('name'))
        if not parser:
            logger.error("Unable to detect which parser to use for the file %s." % filename)
            continue

        # now read the source file
        toREFs = parser(filename=filename, buffer=None)
        if toREFs:
            # next parse the references
            parsed_references = toREFs.process_and_dispatch()
            if not parsed_references:
                logger.error("Unable to parse %s." % toREFs.filename)
                continue

            for block_references in parsed_references:
                # save the initial records in the database,
                # this is going to be useful since it allows us to be able to tell if
                # anything went wrong with the service that we did not get back the
                # resolved reference
                references = app.populate_tables_pre_resolved_initial_status(source_bibcode=block_references['bibcode'],
                                                                             source_filename=filename,
                                                                             parsername=parser_dict.get('name'),
                                                                             references=block_references['references'])
                if not references:
                    logger.error("Unable to insert records from %s to db." % toREFs.filename)
                    continue

                queue_references(references, filename, block_references['bibcode'], parser_dict.get('name'))

        else:
            logger.error("Unable to process %s. Skipped!" % toREFs.filename)


def reprocess_references(reprocess_type: str, score_cutoff: float = 0, match_bibcode: str = '', date_cutoff: time.struct_time = None) -> None:
    """
    reprocesses references by querying the database and sending each reference for processing

    two ways to queue references: one is to read source files, the other is to query database
    this function handles the latter

    :param reprocess_type: the type of query to be performed to get references (e.g., by score, bibstem, year, etc.)
    :param score_cutoff: confidence score below which references will be reprocessed (default is 0)
    :param match_bibcode: bibcode wildcard to match for reprocessing (optional)
    :param date_cutoff: only references after this date will be considered (optional)
    :return: None
    """
    records = app.get_reprocess_records(reprocess_type, score_cutoff, match_bibcode, date_cutoff)
    for record in records:
        # from filename get the parser info
        # file extension, and bibstem and volume directories are used to query database and return the parser info
        # ie for filename `adsrefpipe/tests/unittests/stubdata/txt/ARA+A/0/0000ADSTEST.0.....Z.ref.raw`
        # extension ref.raw, bibstem directory ARA+A and volume directory 0 is used and the
        # parser info is {'name': 'ThreeBibsTxt',
        #                 'extension_pattern': '.ref.raw',
        #                 'reference_service_endpoint': '/text',
        #                 'matches': [[{'journal': 'AnRFM', 'volume_end': 37, 'volume_begin': 34},
        #                              {'journal': 'ARA+A', 'volume_end': 43, 'volume_begin': 40},
        #                              {'journal': 'ARNPS', 'volume_end': 56, 'volume_begin': 52}]]}
        parser_dict = app.get_parser(record['source_filename'])
        # now map parser name to the class (see adsrefpipe/refparsers/handler.py)
        # ie parser name ThreeBibsTxt is mapped to ThreeBibstemsTXTtoREFs
        # 'ThreeBibsTxt': ThreeBibstemsTXTtoREFs,
        # note that from the class name it is clear which type of parser this is
        # (ie, this is a TXT parser implemented in module adsrefpipe/refparsers/ADStxt.py)
        parser = verify(parser_dict.get('name'))
        if not parser:
            logger.error("Unable to detect which parser to use for the file %s." % record['source_filename'])
            continue

        # now pass the result records from query to the parser object
        toREFs = parser(filename=None, buffer=record)
        if toREFs:
            # next parse the references
            parsed_references = toREFs.dispatch()
            if not parsed_references:
                logger.error("Unable to parse %s." % toREFs.filename)
                continue

            for block_references in parsed_references:
                # save the retry records in the database,
                references = app.populate_tables_pre_resolved_retry_status(source_bibcode=block_references['bibcode'],
                                                                           source_filename=record['source_filename'],
                                                                           source_modified=record['source_modified'],
                                                                           retry_records=block_references['references'])
                if not references:
                    logger.error("Unable to reprocess records from file %s." % toREFs.filename)
                    continue

                queue_references(references, toREFs.filename, block_references['bibcode'], parser_dict.get('name'))

        else:
            logger.error("Unable to process %s. Skipped!" % toREFs.filename)


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Process user input.')

    subparsers = parser.add_subparsers(help='commands', dest="action", required=True)

    diagnostics = subparsers.add_parser('DIAGNOSTICS', help='Show diagnostic message')
    diagnostics.add_argument('-b',
                        '--bibcodes',
                        dest='bibcodes',
                        action='store',
                        nargs='+',
                        default=[],
                        help='List of bibcodes separated by spaces')
    diagnostics.add_argument('-s',
                        '--source_filenames',
                        dest='source_filenames',
                        action='store',
                        nargs='+',
                        default=[],
                        help='List of source_filenames separated by spaces')
    diagnostics.add_argument('-p',
                        '--parse_filename',
                        dest='parse_filename',
                        action='store',
                        default=None,
                        help='Verify that the file can be parsed and references resolved')

    resolve = subparsers.add_parser('RESOLVE', help='Resolve references')
    resolve.add_argument('-s',
                        '--source_filenames',
                        dest='source_filenames',
                        action='store',
                        nargs='+',
                        default=[],
                        help='List of source file names (either xml or raw) separated by spaces')
    resolve.add_argument('-p',
                        '--path',
                        dest='path',
                        action='store',
                        default=None,
                        help='Path of source files for resolving')
    resolve.add_argument('-e',
                        '--extension',
                        dest='extension',
                        action='store',
                        default=None,
                        help='Extension of files to locate in the path directory')
    resolve.add_argument('-d',
                        '--days',
                        dest='days',
                        action='store',
                        default=None,
                        help='Resolve only those that are this many days old')
    resolve.add_argument('-c',
                        '--confidence',
                        dest='confidence',
                        action='store',
                        default=None,
                        help='Reprocess resolved records confidence score lower than this value')
    resolve.add_argument('-b',
                        '--bibstem',
                        dest='bibstem',
                        action='store',
                        default=None,
                        help='Reprocess resolved records having this bibstem')
    resolve.add_argument('-y',
                        '--year',
                        dest='year',
                        action='store',
                        default=None,
                        help='Reprocess resolved records having this year')
    resolve.add_argument('-f',
                        '--fail',
                        dest='fail',
                        action='store_true',
                        help='Reprocess records that failed to get resolved')

    stats = subparsers.add_parser('STATS', help='Print out statistics of the reference source file')
    stats.add_argument('-b',
                        '--bibcode',
                        dest='bibcode',
                        action='store',
                        default=None,
                        help='Statistics of source reference, comparing classic and service reference resolvering if available')
    stats.add_argument('-s',
                        '--source_filename',
                        dest='source_filename',
                        action='store',
                        default=None,
                        help='Statistics of source reference, comparing classic and service reference resolvering if available')
    stats.add_argument('-p',
                        '--parser',
                        dest='parser',
                        action='store',
                        default=None,
                        help='To list all source filenames resolved from a specific parser')
    stats.add_argument('-c',
                       '--count',
                       dest='count',
                       action='store_true',
                       help='Print out the count of records in the four main tables')

    query = subparsers.add_parser('QUERY', help='Print out statistics of the reference source file')
    query.add_argument('-b',
                        '--bibcode',
                        dest='bibcode',
                        action='store',
                        default=None,
                        help='Query database by source bibcode, return resolved bibcodes')
    query.add_argument('-a',
                       '--all',
                       dest='all',
                       action='store_true',
                       help='Return all resolved bibcode')

    args = parser.parse_args()

    if args.action == 'DIAGNOSTICS':
        if args.parse_filename:
            name = app.get_parser(args.parse_filename)
            if name:
                logger.info('Source file `%s` shall be parsed using `%s` parser.' % (args.parse_filename, name))
            else:
                logger.error('No parser yet to parse source file `%s`.' % args.parse_filename)
        # either pass in the list of bibcodes, or list of filenames to query db on
        # if neither bibcode nor filenames are supplied, number of records for the tables are displayed
        else:
            run_diagnostics(args.bibcodes, args.source_filenames)

    elif args.action == 'RESOLVE':
        if args.source_filenames:
            process_files(args.source_filenames)
        elif args.path or args.extension:
            if not args.extension:
                logger.error('Both path and extension are required params. Provide extention by -e <extension of files to locate in the path directory>.')
            elif not args.path:
                logger.error('Both path and extension are required params. Provide path by -p <path of source files for resolving>.')
            else:
                # if days has been specified, read it and only consider files with date from today-days,
                # otherwise we are going with everything
                if args.days:
                    date_cutoff = get_date() - timedelta(days=int(args.days))
                else:
                    date_cutoff = get_date('1972')
                source_filenames = get_source_filenames(args.path, args.extension, date_cutoff.timetuple())
                if len(source_filenames) > 0:
                    process_files(source_filenames)
        elif args.confidence:
            date_cutoff = get_date() - timedelta(days=int(args.days)) if args.days else None
            reprocess_references(ReprocessQueryType.score, score_cutoff=float(args.confidence), date_cutoff=date_cutoff)
        elif args.bibstem:
            date_cutoff = get_date() - timedelta(days=int(args.days)) if args.days else None
            reprocess_references(ReprocessQueryType.bibstem, match_bibcode=args.bibstem, date_cutoff=date_cutoff)
        elif args.year:
            date_cutoff = get_date() - timedelta(days=int(args.days)) if args.days else None
            reprocess_references(ReprocessQueryType.year, match_bibcode=args.bibstem, date_cutoff=date_cutoff)
        elif args.fail:
            date_cutoff = get_date() - timedelta(days=int(args.days)) if args.days else None
            reprocess_references(ReprocessQueryType.failed, date_cutoff=date_cutoff)

    # TODO: do we need more command for querying db

    # keeping prints for stats commands, since the user possibly wants to see the replies, instead of seeing them in logs
    elif args.action == 'STATS':
        if args.bibcode or args.source_filename:
            table, num_references, num_resolved = app.get_service_classic_compare_stats_grid(args.bibcode, args.source_filename)
            print('\n',table,'\n')
            print('Num References:', num_references)
            print('Num References Resolved:', num_resolved)
            print('\n')
        elif args.parser:
            records = app.query_reference_source_tbl(parsername=args.parser)
            if not records:
                print('No records found for parser %s.'%args.parser)
            else:
                for record in records:
                    print(record['source_filename'])
        elif args.count:
            results = app.get_count_records()
            print('\n')
            for result in results:
                print('Currently there are %d records in `%s` table, which holds %s.'%(result['count'], result['name'], result['description']))
            print('\n')

    elif args.action == 'QUERY':
        results = app.get_resolved_references('0000PThPS...0.....U')
        for r in results:
            print(r)
        # if args.all:
        # else:

    sys.exit(0)