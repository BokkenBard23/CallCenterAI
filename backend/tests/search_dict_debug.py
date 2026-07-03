"""Debug: search for specific phrases in the dictionary."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'Transcrib'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.xml_parser import parse_xml_file


async def main():
    xml_path = r'data/output/production_xml\sample_dictionary.xml'
    root, val = await parse_xml_file(xml_path)

    def find_conditions(node, path=""):
        for c in node.conditions:
            if 'подключ' in c.text.lower() or 'не хочу' in c.text.lower() or 'не подключ' in c.text.lower():
                print(f"  {path}/{node.name}: phrase=\"{c.text}\" WD={c.word_distance} CH={c.channel_constraint}")
        for ch in node.children:
            find_conditions(ch, f"{path}/{node.name}")

    print("Searching for 'подключ' / 'не хочу' / 'не подключ' in dictionary...")
    find_conditions(root)

    # Also search for 'уйду' and 'оператор'
    print("\nSearching for 'уйду' / 'оператор'...")
    def find_2(node, path=""):
        for c in node.conditions:
            if 'уйду' in c.text.lower() or 'оператор' in c.text.lower():
                print(f"  {path}/{node.name}: phrase=\"{c.text}\" WD={c.word_distance} CH={c.channel_constraint}")
        for ch in node.children:
            find_2(ch, f"{path}/{node.name}")

    find_2(root)


asyncio.run(main())
