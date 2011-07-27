#!/usr/bin/env python
# -*- coding: UTF-8 -*-

"""
Based on read pair mappings, construct contig graph
"""

import sys
import logging

from collections import defaultdict
from optparse import OptionParser

from jcvi.formats.bed import BedLine, pairs
from jcvi.formats.sizes import Sizes
from jcvi.utils.iter import pairwise
from jcvi.utils.range import ranges_intersect
from jcvi.algorithms.graph import nx
from jcvi.algorithms.matrix import determine_signs
from jcvi.apps.base import ActionDispatcher, debug
debug()


def main():

    actions = (
        ('bed', 'construct links from bed file'),
            )
    p = ActionDispatcher(actions)
    p.dispatch(globals())


def bed(args):
    """
    prog bed bedfile fastafile

    Construct contig links based on bed file
    """
    p = OptionParser(bed.__doc__)
    p.add_option("--links", type="int", default=2,
            help="Minimum number of mate pairs to bundle [default: %default]")
    p.add_option("--cutoff", type="int", default=0,
            help="Largest distance expected for linkage " + \
                 "[default: estimate from data]")
    p.add_option("--prefix", default=False, action="store_true",
            help="Only keep links between IDs with same prefix [default: %default]")
    p.add_option("--debug", dest="debug", default=False, action="store_true",
            help="Print verbose info when checking mates [default: %default]")
    opts, args = p.parse_args(args)

    if len(args) != 2:
        sys.exit(p.print_help())

    bedfile, fastafile = args
    links = opts.links
    debug = opts.debug
    cutoff = opts.cutoff

    linksfile = bedfile.rsplit(".", 1)[0] + ".links"

    sizes = Sizes(fastafile)

    cutoffopt = "--cutoff={0}".format(cutoff)
    bedfile, (meandist, stdev, p0, p1, p2) = \
            pairs([bedfile, cutoffopt])

    maxcutoff = cutoff or p2
    logging.debug("Mate hangs must be <= {0}, --cutoff to override".\
            format(maxcutoff))

    contigGraph = defaultdict(list)
    rs = lambda x: x.accn[:-1]

    fp = open(bedfile)

    for a, b in pairwise(fp):
        """
        Criteria for valid contig edge
        1. for/rev do not mapping to the same scaffold (useful for linking)
        2. assuming innie (outie must be flipped first), order the contig pair
        3. calculate sequence hangs, valid hangs are smaller than insert size
        """
        a, b = BedLine(a), BedLine(b)

        if rs(a) != rs(b):
            continue
        pe = rs(a)

        if a.seqid == b.seqid:
            continue

        """
        The algorithm that determines the oNo of this contig pair, the contig
        order is determined by +-, assuming that the matepairs are `innies`. In
        below, we determine the order and orientation by flipping if necessary,
        bringing the strandness of two contigs to the expected +-.
        """
        if a.strand == b.strand:
            if b.strand == "+":  # case: "++", flip b
                b.reverse_complement(sizes)
            else:  # case: "--", flip a
                a.reverse_complement(sizes)

        if b.strand == "+":  # case: "-+"
            a, b = b, a

        assert a.strand == "+" and b.strand == "-"
        """
        ------===----          -----====----
              |_ahang            bhang_|
        """
        aseqid = a.seqid.rstrip('-')
        size = sizes.get_size(aseqid)
        ahang = size - a.start + 1
        bhang = b.end

        if debug:
            print >> sys.stderr, '*' * 60
            print >> sys.stderr, a
            print >> sys.stderr, b
            print >> sys.stderr, "ahang={0} bhang={1}".format(ahang, bhang)

        # Valid links need to be separated by the lib insert
        hangs = ahang + bhang

        if hangs > maxcutoff:
            if debug:
                print >> sys.stderr, "invalid link ({0}). skipped.".format(hangs)
            continue

        # pair (1+, 2-) is the same as (2+, 1-), only do the canonical one
        if a.seqid > b.seqid:
            a.reverse_complement(sizes)
            b.reverse_complement(sizes)
            a, b = b, a

        """
        Ignore redundant mates, in this case if the size of the hangs is seen,
        then it is probably redundant, since independent circularization event
        will give slightly different value)
        """
        if hangs in [x[1] for x in contigGraph[(a.seqid, b.seqid)]]:
            continue

        if opts.prefix:
            aprefix = a.seqid.split("_")[0]
            bprefix = b.seqid.split("_")[0]
            if aprefix != bprefix:
                continue

        contigGraph[(a.seqid, b.seqid)].append((pe, hangs))

    g = nx.Graph()  # use this to get connected components

    for pair, mates in sorted(contigGraph.items()):
        if len(mates) < links:
            continue
        gaps = []
        for mid, hang in mates:
            gmin = max(p1 - hang, 0)
            gmax = p2 - hang
            gaps.append((gmin, gmax))

        aseqid, bseqid = pair
        lastdigits = aseqid[-1] + bseqid[-1]

        if '-' in lastdigits and lastdigits != '--':
            orientation = '-'
        else:
            orientation = '+'

        aseqid, bseqid = aseqid.rstrip('-'), bseqid.rstrip('-')
        g.add_edge(aseqid, bseqid, orientation=orientation)

        gapsize = ranges_intersect(gaps)
        print pair, mates, "orientation:{0} gap:{1}".\
                format(orientation, gapsize)

    for h in nx.connected_component_subgraphs(g):
        solve_component(h)


def solve_component(h):
    nodes, edges = h.nodes(), h.edges(data=True)
    ledges = [(a, b, c["orientation"]) for (a, b, c) in edges]
    N = len(nodes)

    print N, nodes, ledges
    print determine_signs(nodes, ledges)


if __name__ == '__main__':
    main()
