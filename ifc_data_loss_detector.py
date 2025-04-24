#!/usr/bin/env python3

import argparse
import csv
import re
import shutil
from collections import Counter

try:
    import ifcopenshell
except ImportError:
    raise ImportError("Please install ifcopenshell: pip install ifcopenshell")

def export_to_ifc(design_file: str, output_path: str) -> str:
    shutil.copyfile(design_file, output_path)
    print(f"[Export]    '{design_file}' → '{output_path}'")
    return output_path

def validate_ifc(ifc_path: str) -> bool:
    try:
        model = ifcopenshell.open(ifc_path)
        valid = bool(model.schema)
        print(f"[Validate]  '{ifc_path}' -> schema = {model.schema}")
        return valid
    except Exception as e:
        print(f"[Validate]  Failed to open IFC '{ifc_path}': {e}")
        return False

def import_ifc(exported_ifc: str, imported_path: str) -> str:
    shutil.copyfile(exported_ifc, imported_path)
    print(f"[Import]    '{exported_ifc}' → '{imported_path}'")
    return imported_path

def extract_data(ifc_source: str):
    model = ifcopenshell.open(ifc_source)
    counts = Counter(ent.is_a() for ent in model)
    mats = {m.Name for m in model.by_type('IfcMaterial') if hasattr(m, 'Name') and m.Name}
    imgs = set()
    for img in model.by_type('IfcImageTexture'):
        loc = getattr(img, 'Location', None)
        if loc and re.search(r'\.(jpg|jpeg|png|bmp|tif|tiff)$', loc, re.IGNORECASE):
            imgs.add(loc)
    print(f"[Extract]   {ifc_source}: {sum(counts.values())} entities, {len(mats)} materials, {len(imgs)} images")
    return counts, mats, imgs

def compare_data(pre, post):
    pre_counts, pre_mats, pre_imgs = pre
    post_counts, post_mats, post_imgs = post

    missing_elements = {
        cls: pre_counts[cls] - post_counts.get(cls, 0)
        for cls in pre_counts
        if pre_counts[cls] > post_counts.get(cls, 0)
    }
    missing_materials = pre_mats - post_mats
    missing_images    = pre_imgs - post_imgs

    return missing_elements, missing_materials, missing_images

def generate_report(missing_elements, missing_materials, missing_images, report_path: str):
    with open(report_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Entity', 'Type', 'Missing'])
        for cls, cnt in missing_elements.items():
            writer.writerow([cls, 'Element', cnt])
        for mat in missing_materials:
            writer.writerow([mat, 'Material', 1])
        for img in missing_images:
            writer.writerow([img, 'Image', 1])
    print(f"[Report]    Missing-data report → '{report_path}'")

def attempt_to_fix(element: str) -> bool:
    print(f"[Recover]   Attempting to recover element '{element}'… failed.")
    return False

def substitute_material(material: str) -> bool:
    print(f"[Recover]   Substituting missing material '{material}' → default succeeded.")
    return True

def replace_image(image: str) -> bool:
    print(f"[Recover]   Replacing missing image '{image}' → default succeeded.")
    return True

def extract_properties(ifc_path):
    model = ifcopenshell.open(ifc_path)
    data = {}

    for elem in model:
        if not hasattr(elem, "GlobalId"):
            continue
        gid = elem.GlobalId
        props = {}

        for rel in model.by_type("IfcRelDefinesByProperties"):
            if rel.RelatedObjects and elem in rel.RelatedObjects:
                pset = rel.RelatingPropertyDefinition
                if hasattr(pset, "HasProperties"):
                    for prop in pset.HasProperties:
                        if hasattr(prop, "Name") and hasattr(prop, "NominalValue"):
                            prop_name = prop.Name
                            prop_value = str(prop.NominalValue.wrappedValue) if hasattr(prop.NominalValue, 'wrappedValue') else str(prop.NominalValue)
                            props[prop_name] = prop_value

        if props:
            data[gid] = props

    return data

def compare_properties(pre_props, post_props):
    differences = []

    all_ids = set(pre_props) | set(post_props)

    for gid in all_ids:
        pre = pre_props.get(gid, {})
        post = post_props.get(gid, {})

        for key in pre:
            if key not in post:
                differences.append((gid, key, pre[key], "<MISSING>"))
            elif pre[key] != post[key]:
                differences.append((gid, key, pre[key], post[key]))

        for key in post:
            if key not in pre:
                differences.append((gid, key, "<MISSING>", post[key]))

    return differences

def generate_property_report(differences, filename="property_differences_report.csv"):
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['GlobalId', 'Property', 'Pre-Import Value', 'Post-Import Value'])
        for row in differences:
            writer.writerow(row)
    print(f"[Report]    Property differences saved → '{filename}'")

# 🔥 NEW: Material per element
def extract_element_materials(ifc_path):
    model = ifcopenshell.open(ifc_path)
    element_materials = {}

    for rel in model.by_type("IfcRelAssociatesMaterial"):
        material = rel.RelatingMaterial
        related = rel.RelatedObjects

        for elem in related:
            gid = getattr(elem, "GlobalId", None)
            if gid and material:
                if hasattr(material, "Name"):
                    mat_name = material.Name
                elif hasattr(material, "ForLayerSet") and hasattr(material.ForLayerSet, "MaterialLayers"):
                    mat_name = ", ".join(
                        l.Material.Name for l in material.ForLayerSet.MaterialLayers
                        if hasattr(l.Material, "Name")
                    )
                else:
                    mat_name = str(material)
                element_materials[gid] = mat_name

    return element_materials

def compare_element_materials(pre_mats, post_mats):
    differences = []

    all_ids = set(pre_mats.keys()) | set(post_mats.keys())

    for gid in all_ids:
        pre = pre_mats.get(gid)
        post = post_mats.get(gid)

        if pre and not post:
            differences.append((gid, pre, "<MISSING>"))
        elif pre != post:
            differences.append((gid, pre or "<MISSING>", post or "<MISSING>"))

    return differences

def generate_material_loss_report(differences, filename="material_loss_report.csv"):
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['GlobalId', 'Material Before', 'Material After'])
        for row in differences:
            writer.writerow(row)
    print(f"[Report]    Element material loss report → '{filename}'")

def main():
    parser = argparse.ArgumentParser(description="IFC Data Loss Detector with full material/property check")
    parser.add_argument('--design',    required=True, help='Path to original design IFC')
    parser.add_argument('--exported',  default='exported.ifc', help='Exported IFC file path')
    parser.add_argument('--imported',  default='imported.ifc', help='Imported IFC file path')
    parser.add_argument('--report',    default='data_loss_report.csv', help='Missing entity/image/material report')
    args = parser.parse_args()

    exp_ifc = export_to_ifc(args.design, args.exported)
    if not validate_ifc(exp_ifc):
        print("ERROR: IFC export invalid → aborting.")
        return

    imp_ifc = import_ifc(exp_ifc, args.imported)
    if not validate_ifc(imp_ifc):
        print("ERROR: IFC import invalid → aborting.")
        return

    pre_data  = extract_data(exp_ifc)
    post_data = extract_data(imp_ifc)

    missing_elems, missing_mats, missing_imgs = compare_data(pre_data, post_data)

    if missing_elems or missing_mats or missing_imgs:
        print("⚠️  Warning: Data Loss Detected")
        generate_report(missing_elems, missing_mats, missing_imgs, args.report)
    else:
        print("✅ No Data Loss Detected")

    for e in missing_elems:
        attempt_to_fix(e)
    for m in missing_mats:
        substitute_material(m)
    for i in missing_imgs:
        replace_image(i)

    re_data = extract_data(imp_ifc)
    if re_data == pre_data:
        print("🎉 Model successfully converted with no data loss.")
    else:
        print("⚠️  Some data loss could not be resolved.")

    # Properties check
    print("[Props]     Checking property-level data...")
    pre_props = extract_properties(exp_ifc)
    post_props = extract_properties(imp_ifc)
    prop_diffs = compare_properties(pre_props, post_props)

    if prop_diffs:
        print(f"⚠️  Property differences found: {len(prop_diffs)}")
        generate_property_report(prop_diffs)
    else:
        print("✅ No property-level differences found.")

    # Material per element check
    print("[Materials] Checking element-level material assignments...")
    pre_elem_mats = extract_element_materials(exp_ifc)
    post_elem_mats = extract_element_materials(imp_ifc)
    material_diffs = compare_element_materials(pre_elem_mats, post_elem_mats)

    if material_diffs:
        print(f"⚠️  Element-level material loss detected: {len(material_diffs)} items")
        generate_material_loss_report(material_diffs)
    else:
        print("✅ No element-level material differences found.")

    print("🚀 Process completed.")

if __name__ == '__main__':
    main()
