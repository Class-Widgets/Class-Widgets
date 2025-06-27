import re
from collections import defaultdict
import os

input_dir = './i18n'
output_suffix = '_fixed.ts'

for filename in os.listdir(input_dir):
    if filename.endswith('.ts') and not filename.endswith(output_suffix):
        input_file = os.path.join(input_dir, filename)
        output_file = os.path.join(input_dir, filename[:-3] + output_suffix)
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()
        # 保留头部和尾部
        header = content.split('<context>', 1)[0]
        contexts = re.findall(r'<context>.*?</context>', content, re.DOTALL)
        footer = content.split('</context>')[-1]
        # name -> list of messages
        name2msgs = defaultdict(list)
        for ctx in contexts:
            name_match = re.search(r'<name>(.*?)</name>', ctx, re.DOTALL)
            name = name_match.group(1).strip() if name_match else ''
            if name == '':
                # 空name，拆分每个message
                messages = re.findall(r'<message>.*?</message>', ctx, re.DOTALL)
                for msg in messages:
                    src_match = re.search(r'<source>(.*?)</source>', msg, re.DOTALL)
                    cmt_match = re.search(r'<comment>(.*?)</comment>', msg, re.DOTALL)
                    if src_match and cmt_match:
                        new_name = src_match.group(1).strip()
                        if new_name == 'list':
                            new_name = 'list_'
                        new_source = cmt_match.group(1).strip()
                        # 替换
                        new_msg = re.sub(r'<source>.*?</source>', f'<source>{new_source}</source>', msg, count=1, flags=re.DOTALL)
                        # 规范缩进
                        new_msg = re.sub(r'^(\s*)<', '        <', new_msg, flags=re.MULTILINE)
                        name2msgs[new_name].append(new_msg)
            else:
                # 非空name，收集所有message
                if name == 'list':
                    name = 'list_'
                messages = re.findall(r'<message>.*?</message>', ctx, re.DOTALL)
                for msg in messages:
                    # 规范缩进
                    msg = re.sub(r'^(\s*)<', '        <', msg, flags=re.MULTILINE)
                    name2msgs[name].append(msg)
        # 生成新的 context
        new_contexts = []
        for name, msgs in name2msgs.items():
            ctx = f'<context>\n    <name>{name}</name>\n' + '\n'.join(msgs) + '\n</context>'
            new_contexts.append(ctx)
        # 拼接
        result = header + ''.join(new_contexts) + footer
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(result)
        print(f'已处理: {filename} -> {os.path.basename(output_file)}')