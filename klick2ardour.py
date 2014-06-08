#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# klick2ardour.py - converts a klick tempomap to an ardour session
#
# Copyright (C) 2008  Dominic Sacré  <dominic.sacre@gmx.de>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#

import sys
import math
import re
import xml.etree.ElementTree as ET


class struct:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class KlickTempomapReader:
    regex = re.compile(
        '^(\s*(?P<label>[\w-]+):)?' \
        '\s*(?P<bars>\d+)' \
        '(\s+(?P<beats>\d+)/(?P<denom>\d+))?' \
        '\s+(?P<tempo>\d+(\.\d+)?)(-(?P<tempo2>\d+(\.\d+)?))?' \
        '(\s+(?P<pattern>[Xx\.]+))?' \
        '(\s+(?P<volume>\d+(\.d+)?))?' \
        '\s*(#.*)?$'
    )
    regex_blank = re.compile('^\s*(#.*)?$')

    def __init__(self, filename):
        self.filename = filename

    def read(self):
        tempomap = [self.parse_entry(line) for line in file(self.filename) if not self.is_blank(line)]
        return tempomap

    def parse_entry(self, line):
        m = re.match(KlickTempomapReader.regex, line)
        if not m:
            sys.exit("couldn't parse tempomap entry:\n%s" % line.strip())

        maybe = lambda x, y: x if x else y

        return struct(
            label  = maybe(m.group('label'), None),
            bars   = int(m.group('bars')),
            beats  = int(maybe(m.group('beats'), 4)),
            denom  = int(maybe(m.group('denom'), 4)),
            tempo  = float(m.group('tempo')),
            tempo2 = float(maybe(m.group('tempo2'), 0.0))
        )

    def is_blank(self, line):
        return re.match(KlickTempomapReader.regex_blank, line) != None


class ArdourTempomapWriter:
    def __init__(self, filename):
        self.filename = filename

        self.tree = ET.parse(self.filename)
        self.session_node = self.tree.getroot()

        self.samplerate = int(self.session_node.attrib['sample-rate'])
        self.id_counter = int(self.session_node.attrib['id-counter'])

    def write(self, tempomap):
        # remove existing tempomap node
        self.session_node.remove(self.session_node.find('TempoMap'))
        self.tempomap_node = ET.SubElement(self.session_node, 'TempoMap')

        self.locations_node = self.session_node.find('Locations')

        # remove existing markers. can't remove while iterating...
        for loc in [x for x in self.locations_node if x.attrib['flags'] == 'IsMark']:
            self.locations_node.remove(loc)

        state = struct(frames = 0, bars = 0, beats = 0, denom = 0, tempo = 0)

        for entry in tempomap:
            self.write_tempomap_entry(state, entry)
            if entry.label:
                self.write_marker(state.frames, entry.label)

            # save current position (frames/bars), meter and tempo
            state = struct(frames = state.frames + self.entry_frames(entry),
                           bars  = state.bars + entry.bars,
                           beats = entry.beats,
                           denom = entry.denom,
                           tempo = entry.tempo if not entry.tempo2 else 0.0)

        self.session_node.attrib['id-counter'] = str(self.id_counter)
        self.tree.write(self.filename)

    def write_tempomap_entry(self, state, entry):
        if entry.tempo != state.tempo and not entry.tempo2:
            # constant tempo
            self.write_tempo(state.bars, 0, entry.tempo)
        elif entry.tempo2:
            # gradual tempo change
            for x in range(entry.bars * entry.beats):
                self.write_tempo(state.bars + x // entry.beats, x % entry.beats, self.average_tempo(entry, x))

        if (entry.beats, entry.denom) != (state.beats, state.denom):
            self.write_meter(state.bars, entry.beats, entry.denom)

    def write_tempo(self, bar, beat, tempo):
        elem = ET.SubElement(self.tempomap_node, 'Tempo')
        elem.attrib['beats-per-minute'] = str(tempo)
        elem.attrib['movable'] = 'yes' if bar != 0 and beat != 0 else 'no'
        elem.attrib['note-type'] = '4'
        elem.attrib['start'] = '%d|%d|0' % (bar+1, beat+1)

    def write_meter(self, bar, beats, denom):
        elem = ET.SubElement(self.tempomap_node, 'Meter')
        elem.attrib['beats-per-bar'] = str(beats)
        elem.attrib['movable'] = 'yes' if bar != 0 else 'no'
        elem.attrib['note-type'] = str(denom)
        elem.attrib['start'] = '%d|1|0' % (bar+1)

    def write_marker(self, frame, label):
        elem = ET.SubElement(self.locations_node, 'Location')
        elem.attrib['name'] = label
        elem.attrib['start'] = str(frame)
        elem.attrib['end'] = str(frame)
        elem.attrib['flags'] = 'IsMark'
        elem.attrib['locked'] = 'no'
        elem.attrib['id'] = str(self.id_counter)
        self.id_counter += 1

    def entry_frames(self, entry):
        if not entry.tempo2:
            t = entry.tempo
        else:
            t = (entry.tempo - entry.tempo2) / (math.log(entry.tempo) - math.log(entry.tempo2))
        secs = entry.bars * entry.beats * 240.0 / (t * entry.denom)
        return secs * self.samplerate

    def average_tempo(self, entry, beat):
        d = entry.tempo2 - entry.tempo
        n = entry.bars * entry.beats
        t1 = entry.tempo + d * beat / n
        t2 = entry.tempo + d * (beat+1) / n
        return (t1 - t2) / (math.log(t1) - math.log(t2))


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] in ("-h", "--help"):
        sys.exit("Usage: klick2ardour.py <tempomap> <ardour-session-file>")

    reader = KlickTempomapReader(sys.argv[1])
    tempomap = reader.read()

    writer = ArdourTempomapWriter(sys.argv[2])
    writer.write(tempomap)
