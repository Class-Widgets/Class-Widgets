#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import glob
import os
import sys
import xml.etree.ElementTree as ET

def read_text(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def write_text(path, text):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)

def extract_preamble(original_text):
    xml_decl = None
    doctype = None
    lines = original_text.splitlines(True)
    for line in lines:
        if line.lstrip().startswith('<?xml'):
            xml_decl = line
        elif line.lstrip().startswith('<!DOCTYPE'):
            doctype = line
        elif line.strip().startswith('<ui'):
            break
    return xml_decl, doctype

def tostring_with_preamble(root, xml_decl, doctype):
    xml_str = ET.tostring(root, encoding='utf-8').decode('utf-8')
    if xml_decl is None:
        xml_decl = '<?xml version="1.0" encoding="UTF-8"?>\n'
    out = xml_decl
    if doctype:
        out += doctype
    out += xml_str if xml_str.startswith('<') else xml_str.lstrip()
    return out

def get_label_classes(root):
    label_classes = {'QLabel'}
    customwidgets = root.find('customwidgets')
    if customwidgets is not None:
        for cw in customwidgets.findall('customwidget'):
            cls = cw.findtext('class')
            ext = cw.findtext('extends')
            if cls and ext and ext.strip() == 'QLabel':
                label_classes.add(cls.strip())
    return label_classes

def ensure_wordwrap_if_absent(widget_elem):
    """仅当没有 wordWrap 属性时才添加 true"""
    for prop in widget_elem.findall('property'):
        if prop.get('name') == 'wordWrap':
            # 如果已经存在，不改动
            return False, False
    # 添加新属性
    prop = ET.Element('property', {'name': 'wordWrap'})
    bool_elem = ET.Element('bool')
    bool_elem.text = 'true'
    prop.append(bool_elem)
    widget_elem.append(prop)
    return True, True

def is_label_candidate(widget_elem, label_classes):
    cls = widget_elem.get('class', '')
    return cls in label_classes

def process_ui_file(path, dry_run=False, backup=True, verbose=True):
    original = read_text(path)
    xml_decl, doctype = extract_preamble(original)

    try:
        root = ET.fromstring(original)
    except ET.ParseError as e:
        if verbose:
            print(f'[SKIP] {path}: XML parse error: {e}')
        return 0, 0

    label_classes = get_label_classes(root)
    modified_count = 0
    added_count = 0

    for widget in root.iter('widget'):
        if is_label_candidate(widget, label_classes):
            modified, newly_added = ensure_wordwrap_if_absent(widget)
            if modified:
                modified_count += 1
                if newly_added:
                    added_count += 1

    if modified_count == 0:
        if verbose:
            print(f'[OK]   {path}: no changes needed')
        return 0, 0

    out_text = tostring_with_preamble(root, xml_decl, doctype)

    if dry_run:
        if verbose:
            print(f'[DRY]  {path}: would modify {modified_count} label(s), add {added_count} wordWrap prop(s)')
        return modified_count, added_count

    if backup:
        bak = path + '.bak'
        if not os.path.exists(bak):
            write_text(bak, original)

    write_text(path, out_text)
    if verbose:
        print(f'[SAVE] {path}: modified {modified_count} label(s), added {added_count} wordWrap prop(s)')
    return modified_count, added_count

def main():
    parser = argparse.ArgumentParser(
        description='Add wordWrap=true for QLabel & subclasses only if absent (Qt + QFluentWidgets compatible).'
    )
    parser.add_argument('-r', '--recursive', action='store_true', help='Search .ui files recursively')
    parser.add_argument('--dry-run', action='store_true', help='Do not write changes, only report')
    parser.add_argument('--no-backup', action='store_true', help='Do not write .bak backup files')
    parser.add_argument('--glob', default='*.ui', help='Glob pattern (default: *.ui)')
    parser.add_argument('--quiet', action='store_true', help='Less verbose output')

    args = parser.parse_args()

    pattern = ('**/' if args.recursive else '') + args.glob
    files = sorted(glob.glob(pattern, recursive=args.recursive))

    if not files:
        print('[INFO] No .ui files found with pattern:', pattern)
        sys.exit(0)

    total_mod = 0
    total_add = 0
    for f in files:
        if not os.path.isfile(f):
            continue
        m, a = process_ui_file(
            f,
            dry_run=args.dry_run,
            backup=not args.no_backup,
            verbose=not args.quiet
        )
        total_mod += m
        total_add += a

    if not args.quiet:
        print(f'[DONE] Files: {len(files)}, Labels changed: {total_mod}, wordWrap added: {total_add}')
    if args.dry_run and total_mod > 0:
        sys.exit(2)

if __name__ == '__main__':
    main()
