import yaml
from glob import glob
from wordnet import *
from change_manager import escape_lemma, synset_key
from yaml import CLoader
import codecs
import os
from collections import defaultdict

entry_orders = {}

def map_sense_key(sk):
    return sk

def make_pos(y, pos):
    if "adjposition" in y: 
        return y["adjposition"] + "-" + pos 
    else: 
        return pos

def make_sense_id(y, lemma, pos):
    return "ewn-%s-%s-%s" % (
        escape_lemma(lemma), make_pos(y, pos), y["synset"][:-2])

def sense_from_yaml(y, lemma, pos, n):
    s = Sense(make_sense_id(y,lemma,pos),
        "ewn-" + y["synset"], map_sense_key(y["id"]), n,
        y.get("adjposition"))
    for rel, targets in y.items():
        if rel in SenseRelType._value2member_map_:
            for target in targets:
                # Remap senses
                s.add_sense_relation(SenseRelation(
                    map_sense_key(target), SenseRelType(rel)))
    return s

def synset_from_yaml(props, id, lex_name):
    if "partOfSpeech" not in props:
        print(props)
    ss = Synset("ewn-" + id,
            props.get("ili", "in"),
            PartOfSpeech(props["partOfSpeech"]),
            lex_name,
            props.get("source"))
    for defn in props["definition"]:
        ss.add_definition(Definition(defn))
    if "ili" not in props:
        ss.add_definition(Definition(props["definition"][0]), True)
    for example in props.get("example", []):
        if isinstance(example, str):
            ss.add_example(Example(example))
        else:
            ss.add_example(Example(example["text"], example["source"]))
    for rel, targets in props.items():
        if rel in SynsetRelType._value2member_map_:
            for target in targets:
                ss.add_synset_relation(SynsetRelation(
                    "ewn-" + target, SynsetRelType(rel)))
    return ss

def syntactic_behaviour_from_yaml(frames, props, lemma, pos):
    keys = set([subcat for sense in props["sense"] for subcat in sense.get("subcat",[])])
    return [
            SyntacticBehaviour(frames[k],
                [make_sense_id(sense,lemma,pos) for sense in props["sense"] if k in sense.get("subcat", [])])
                for k in keys]

def fix_sense_id(sense, lemma, key2id, key2oldid,synset_ids_starting_from_zero):
    key2oldid[sense.sense_key] = sense.id
    idx = entry_orders[sense.synset[4:]].index(lemma)
    if sense.synset in synset_ids_starting_from_zero:
        sense.id = "%s-%02d" % (sense.id, idx)
    else:
        sense.id = "%s-%02d" % (sense.id, idx+1)
    key2id[sense.sense_key] = sense.id

def fix_sense_rels(wn, sense, key2id, key2oldid):
    for rel in sense.sense_relations:
        if not rel.target.startswith("ewn-"):
           target_id = key2oldid[rel.target]
           rel.target = key2id[rel.target]
           if (rel.rel_type in inverse_sense_rels 
               and inverse_sense_rels[rel.rel_type] != rel.rel_type):
               wn.sense_by_id(target_id).add_sense_relation(
                       SenseRelation(sense.id,
                           inverse_sense_rels[rel.rel_type]))

def fix_synset_rels(wn, synset):
    for rel in synset.synset_relations:
        if (rel.rel_type in inverse_synset_rels
                and inverse_synset_rels[rel.rel_type] != rel.rel_type):
            target_synset = wn.synset_by_id(rel.target)
            if not [sr for sr in target_synset.synset_relations
                    if sr.target == synset.id and sr.rel_type == inverse_synset_rels[rel.rel_type]]:
                target_synset.add_synset_relation(
                        SynsetRelation(synset.id,
                            inverse_synset_rels[rel.rel_type]))

def main():
    wn = Lexicon("ewn", "Engish WordNet", "en", 
            "english-wordnet@googlegroups.com",
            "https://creativecommons.org/licenses/by/4.0",
            "2020",
            "https://github.com/globalwordnet/english-wordnet")
    with open("src/yaml/frames.yaml") as inp:
        frames = yaml.load(inp, Loader=CLoader)
    for f in glob("src/yaml/entries-*.yaml"):
        with open(f) as inp:
            y = yaml.load(inp, Loader=CLoader)

            for lemma, pos_map in y.items():
                for pos, props in pos_map.items():
                    entry = LexicalEntry(
                            "ewn-%s-%s" % (escape_lemma(lemma), pos))
                    entry.set_lemma(Lemma(lemma, PartOfSpeech(pos)))
                    if "form" in props:
                        for form in props["form"]:
                            entry.add_form(Form(form))
                    for n, sense in enumerate(props["sense"]):
                        entry.add_sense(sense_from_yaml(sense, lemma, pos, n))
                    entry.syntactic_behaviours = syntactic_behaviour_from_yaml(frames, props, lemma, pos)
                    wn.add_entry(entry)

    for f in glob("src/yaml/*.yaml"): 
        lex_name = f[9:-5]
        if "entries" not in f and "frames" not in f:
            with open(f) as inp:
                y = yaml.load(inp, Loader=CLoader)

                for id, props in y.items():
                    wn.add_synset(synset_from_yaml(props, id, lex_name))
                    entry_orders[id] = props["members"]

    # This is a big hack because of some inconsistencies in the XML that should
    # be gone soon
    synset_ids_starting_from_zero = set()
    for f in glob("src/xml/*.xml"):
        wn_lex = parse_wordnet(f)
        for entry in wn_lex.entries:
            for sense in entry.senses:
                if sense.id.endswith("00"):
                    synset_ids_starting_from_zero.add(sense.synset)


    key2id = {}
    key2oldid = {}
    for entry in wn.entries:
        for sense in entry.senses:
            fix_sense_id(sense, entry.lemma.written_form, key2id, key2oldid, synset_ids_starting_from_zero)

    for entry in wn.entries:
        for sense in entry.senses:
            fix_sense_rels(wn, sense, key2id, key2oldid)

    for synset in wn.synsets:
        fix_synset_rels(wn, synset)

    with codecs.open("wn-from-yaml.xml","w","utf-8") as outp:
        wn.to_xml(outp, True)

    by_lex_name = {}
    for synset in wn.synsets:
        if synset.lex_name not in by_lex_name:
            by_lex_name[synset.lex_name] = Lexicon(
                    "ewn", "English WordNet", "en",
                    "john@mccr.ae", "https://wordnet.princeton.edu/license-and-commercial-use",
                    "2019","https://github.com/globalwordnet/english-wordnet")
        by_lex_name[synset.lex_name].add_synset(synset)
        
    for entry in wn.entries:
        sense_no = dict([(e.id,i) for i,e in enumerate(entry.senses)])
        for lex_name in by_lex_name.keys():
            senses = [sense for sense in entry.senses if wn.synset_by_id(sense.synset).lex_name == lex_name]
            if senses:
                e = LexicalEntry(entry.id)
                e.set_lemma(entry.lemma)
                for f in entry.forms:
                    e.add_form(f)
                for s in senses:
                    s.n = sense_no[s.id]
                    e.add_sense(s)
                def find_sense_for_sb(sb_sense):
                    for sense2 in senses:
                        if sense2.id[:-3] == sb_sense:
                            return sense2.id
                    return None
                e.syntactic_behaviours = [SyntacticBehaviour(
                    sb.subcategorization_frame,
                    [find_sense_for_sb(sense) for sense in sb.senses])
                    for sb in entry.syntactic_behaviours]
                e.syntactic_behaviours = [SyntacticBehaviour(
                    sb.subcategorization_frame, [s for s in sb.senses if s])
                    for sb in e.syntactic_behaviours if any(sb.senses)]
                by_lex_name[lex_name].add_entry(e)

    for lex_name, wn in by_lex_name.items():
        if os.path.exists("src/xml/wn-%s.xml" % lex_name):
            wn_lex = parse_wordnet("src/xml/wn-%s.xml" % lex_name)
            senseids = { sense.id[:-2]: sense.id for entry in wn_lex.entries for sense in entry.senses }
            wn.comments = wn_lex.comments
            entry_order = defaultdict(lambda: 10000000,[(e,i) for i,e in enumerate(entry.id for entry in wn_lex.entries)])
            wn.entries = sorted(wn.entries, key=lambda e: entry_order[e.id])
            for entry in wn.entries:
                if wn_lex.entry_by_id(entry.id):
                    # Fix the last ID, because it is not actually so predicatable in the XML
                    for sense in entry.senses:
                        sense.id = senseids.get(sense.id[:-2], sense.id)
                    sense_order = defaultdict(lambda: 10000, [(e,i) for i,e in enumerate(sense.id for sense in wn_lex.entry_by_id(entry.id).senses)])
                    entry.senses = sorted(entry.senses, key=lambda s: sense_order[s.id])
                    # This is a bit of a hack as some of the n values are not continguous 
                    for sense in entry.senses:
                        if wn_lex.sense_by_id(sense.id):
                            sense.n = wn_lex.sense_by_id(sense.id).n 
                            sense_rel_order = defaultdict(lambda: 10000, [((sr.target,sr.rel_type), i)
                                for i, sr in enumerate(wn_lex.sense_by_id(sense.id).sense_relations)])
                            sense.sense_relations = sorted(sense.sense_relations, 
                                key=lambda sr: sense_rel_order[(sr.target,sr.rel_type)])
                        else:
                            print("sense not found:" + sense.id)
                    sb_order = defaultdict(lambda: 10000, [(e,i) for i,e in enumerate(sb.subcategorization_frame for sb in wn_lex.entry_by_id(entry.id).syntactic_behaviours)])
                    entry.syntactic_behaviours = sorted(entry.syntactic_behaviours,
                            key=lambda sb: sb_order[sb.subcategorization_frame])
                    for sb in entry.syntactic_behaviours:
                        sb2s = [sb2 for sb2 in wn_lex.entry_by_id(entry.id).syntactic_behaviours
                                    if sb2.subcategorization_frame == sb.subcategorization_frame]
                        if sb2s:
                            sbe_order = defaultdict(lambda: 10000, [(e,i) 
                                for i,e in enumerate(sb2s[0].senses)])
                            sb.senses = sorted(sb.senses, key=lambda s: sbe_order[s])
                else:
                    print("not found:" + entry.id)
            synset_order = defaultdict(lambda: 1000000, [(e,i) for i,e in enumerate(
                synset.id for synset in wn_lex.synsets)])
            wn.synsets = sorted(wn.synsets, key=lambda s: synset_order[s.id])
            for synset in wn.synsets:
                if wn_lex.synset_by_id(synset.id):
                    synset_rel_order = defaultdict(lambda: 10000, [((sr.target, sr.rel_type), i)
                        for i, sr in enumerate(wn_lex.synset_by_id(synset.id).synset_relations)])
                    synset.synset_relations = sorted(synset.synset_relations,
                        key=lambda sr: synset_rel_order[(sr.target, sr.rel_type)])
        with codecs.open("src/xml/wn-%s.xml" % lex_name,"w","utf-8") as outp:
            wn.to_xml(outp, True)

if __name__ == "__main__":
    main()
