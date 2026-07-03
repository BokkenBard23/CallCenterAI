"""Deep check of real XML parsing — traverse tree and check enriched fields at all levels."""
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'Transcrib'))

from app.services.xml_parser import parse_xml_bytes


def check_node(node, depth=0):
    """Recursively check a node and its children, returning check results."""
    indent = "  " * depth
    results = []

    # Check phrase_groups
    has_phrases = len(node.phrase_groups) > 0
    has_conditions = len(node.conditions) > 0
    has_attrs = node.attributes is not None and any(
        t.type == "ATTRIBUTE" for t in node.attributes.attribute_tokens
    )

    # Exact flags on conditions
    exact_conds = [c for c in node.conditions if c.is_exact]
    non_exact_conds = [c for c in node.conditions if not c.is_exact]

    print(f"{indent}Node: id={node.id[:12]}..., name={node.name[:40] if node.name else 'N/A'}")
    print(f"{indent}  conditions={len(node.conditions)}, phrase_groups={len(node.phrase_groups)}, "
          f"children={len(node.children)}, is_remainder={node.is_remainder}")
    print(f"{indent}  saved_state: {'present' if node.saved_state else 'None'}, "
          f"attributes: {'present' if node.attributes else 'None'}, "
          f"attribute_tree: {'present' if node.attribute_tree else 'None'}")
    print(f"{indent}  exact_conditions={len(exact_conds)}, non_exact_conditions={len(non_exact_conds)}")

    if node.phrase_groups:
        for i, pg in enumerate(node.phrase_groups[:3]):
            print(f"{indent}    PhraseGroup[{i}]: words={pg.words[:5]}, channel={pg.channel}, "
                  f"wd={pg.word_distance}, is_exact={pg.is_exact}")

    if exact_conds:
        for c in exact_conds[:2]:
            print(f"{indent}    EXACT: text='{c.text[:50]}', wd={c.word_distance}, ch={c.channel_constraint}")

    # Track key findings
    results.append({
        "node_name": node.name[:40] if node.name else node.id[:12],
        "has_conditions": has_conditions,
        "has_phrase_groups": has_phrases,
        "has_attributes": has_attrs,
        "has_attribute_tree": node.attribute_tree is not None,
        "has_saved_state": node.saved_state is not None,
        "is_remainder": node.is_remainder,
        "exact_count": len(exact_conds),
    })

    for child in node.children:
        results.extend(check_node(child, depth + 1))

    return results


async def main():
    xml_dir = r'data/input/ins'
    if not os.path.isdir(xml_dir):
        print(f"XML dir not found: {xml_dir}")
        return False

    xml_files = [f for f in os.listdir(xml_dir) if f.endswith('.xml')]
    print(f"Found {len(xml_files)} XML files\n")

    all_results = []
    all_ok = True

    for fname in xml_files[:2]:
        fpath = os.path.join(xml_dir, fname)
        with open(fpath, 'rb') as f:
            data = f.read()
        print(f"{'=' * 60}")
        print(f"FILE: {fname} ({len(data)} bytes)")
        print(f"{'=' * 60}")

        try:
            node, validation = await parse_xml_bytes(data, fname)
            results = check_node(node)
            all_results.extend(results)

            # Summary checks
            nodes_with_conditions = [r for r in results if r["has_conditions"]]
            nodes_with_phrases = [r for r in results if r["has_phrase_groups"]]
            nodes_with_exact = [r for r in results if r["exact_count"] > 0]
            nodes_with_attrs = [r for r in results if r["has_attributes"]]
            nodes_with_tree = [r for r in results if r["has_attribute_tree"]]
            nodes_with_saved_state = [r for r in results if r["has_saved_state"]]
            remainder_nodes = [r for r in results if r["is_remainder"]]

            print(f"\n--- Summary for {fname[:30]} ---")
            print(f"  Total nodes: {len(results)}")
            print(f"  Nodes with conditions: {len(nodes_with_conditions)}")
            print(f"  Nodes with phrase_groups: {len(nodes_with_phrases)}")
            print(f"  Nodes with exact matches: {len(nodes_with_exact)}")
            print(f"  Nodes with attributes: {len(nodes_with_attrs)}")
            print(f"  Nodes with attribute_tree: {len(nodes_with_tree)}")
            print(f"  Nodes with saved_state: {len(nodes_with_saved_state)}")
            print(f"  Remainder nodes: {len(remainder_nodes)}")

            # Key verdicts
            if not nodes_with_conditions:
                print(f"  [WARN] No nodes with conditions found in this dictionary")
            if not nodes_with_phrases:
                print(f"  [WARN] No nodes with phrase_groups found in this dictionary")
            if not nodes_with_saved_state:
                print(f"  [FAIL] No nodes with saved_state — parsing issue?")
                all_ok = False
            else:
                print(f"  [PASS] saved_state populated at {len(nodes_with_saved_state)} nodes")

            if nodes_with_attrs:
                print(f"  [PASS] Attributes found at {len(nodes_with_attrs)} nodes")
            if nodes_with_tree:
                print(f"  [PASS] Attribute tree built at {len(nodes_with_tree)} nodes")

        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            all_ok = False

    print(f"\n{'=' * 60}")
    print(f"OVERALL: {'ALL KEY CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED'}")
    return all_ok


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
