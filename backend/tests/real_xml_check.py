"""Real XML file parsing verification — checks enriched fields from dict-analyzer integration."""
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'Transcrib'))

from app.services.xml_parser import parse_xml_bytes


async def test_real_xml():
    xml_dir = r'data/input/ins'
    if not os.path.isdir(xml_dir):
        print(f"XML dir not found: {xml_dir}")
        return

    xml_files = [f for f in os.listdir(xml_dir) if f.endswith('.xml')]
    print(f"Found {len(xml_files)} XML files")

    all_ok = True

    for fname in xml_files[:2]:
        fpath = os.path.join(xml_dir, fname)
        with open(fpath, 'rb') as f:
            data = f.read()
        print(f"\n=== {fname} ({len(data)} bytes) ===")

        try:
            node, validation = await parse_xml_bytes(data, fname)
            print(f"  Root ID: {node.id}")
            print(f"  Root Name: {node.name}")
            print(f"  Conditions: {len(node.conditions)}")
            print(f"  Children: {len(node.children)}")

            # SavedState check
            ss = node.saved_state
            print(f"  saved_state: total_found={ss.total_found if ss else 'N/A'}, "
                  f"is_actual={ss.is_actual if ss else 'N/A'}")

            # is_remainder
            print(f"  is_remainder: {node.is_remainder}")

            # PhraseGroups
            print(f"  phrase_groups: {len(node.phrase_groups)}")

            # Attributes
            attrs_status = "present" if node.attributes else "None"
            print(f"  attributes: {attrs_status}")
            if node.attributes:
                attr_tokens = node.attributes.attribute_tokens
                print(f"    attribute_tokens: {len(attr_tokens)}")
                attr_count = sum(1 for t in attr_tokens if t.type == "ATTRIBUTE")
                print(f"    meaningful attributes: {attr_count}")

            # Attribute tree
            tree_status = "present" if node.attribute_tree else "None"
            print(f"  attribute_tree: {tree_status}")
            if node.attribute_tree:
                print(f"    tree root type: {node.attribute_tree.node_type}")
                print(f"    tree children: {len(node.attribute_tree.children)}")

            # TERMINAL quotes -> is_exact
            exact_count = sum(1 for c in node.conditions if c.is_exact)
            print(f"  Exact conditions: {exact_count}/{len(node.conditions)}")

            # Children for remainder
            remainder_children = sum(1 for c in node.children if c.is_remainder)
            print(f"  Remainder children: {remainder_children}/{len(node.children)}")

            # Validation
            print(f"  Validation: valid={validation.valid}, "
                  f"warnings={len(validation.warnings)}, errors={len(validation.errors)}")
            if validation.warnings[:3]:
                for w in validation.warnings[:3]:
                    print(f"    Warning: {w}")

            # Check key enriched fields exist
            checks = {
                "saved_state exists": ss is not None,
                "phrase_groups populated": len(node.phrase_groups) > 0,
                "is_remainder default False": node.is_remainder is False,
                "attribute_tree exists (if attrs present)": (
                    node.attribute_tree is not None if node.attributes and
                    any(t.type == "ATTRIBUTE" for t in node.attributes.attribute_tokens)
                    else True
                ),
            }
            for check_name, passed in checks.items():
                status = "PASS" if passed else "FAIL"
                print(f"  [{status}] {check_name}")
                if not passed:
                    all_ok = False

            # Check some children for remainder
            if node.children:
                child = node.children[0]
                print(f"  First child: name={child.name}, is_remainder={child.is_remainder}")
                if child.saved_state:
                    print(f"    child saved_state: total_found={child.saved_state.total_found}")

        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            all_ok = False

    print(f"\n{'=' * 50}")
    print(f"Overall result: {'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED'}")
    return all_ok


if __name__ == "__main__":
    result = asyncio.run(test_real_xml())
    sys.exit(0 if result else 1)
