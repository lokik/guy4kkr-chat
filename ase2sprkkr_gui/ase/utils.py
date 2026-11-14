import numpy as np
import re

def labels_for_partitions(atoms, partitions=None, sep='_'):
    """Generate unique labels for atom kinds, appending suffixes as needed."""
    try:
        arr = atoms.get_array('labels')
    except KeyError:
        arr = atoms.symbols
    partitions = partition_by_kinds(atoms) if partitions is None else partitions
    firsts = [ i[0] for i in partitions ]
    arr = arr[firsts]

    used = set()
    result = []

    for label in arr:
        label = re.sub(r"\.\d+$", "", label)
        if label not in used:
            result.append(label)
            used.add(label)
        else:
            i = 1
            while f"{label}{sep}{i}" in used:
                i += 1
            new_label = f"{label}{sep}{i}"
            result.append(new_label)
            used.add(new_label)
    return result

def partition_by_kinds(atoms):
    """Partition atoms by their spacegroup kinds.

    Returns a dict mapping kind index to list of atom indices.
    """
    if not 'spacegroup_kinds' in atoms.arrays:
        return np.arange(len(atoms)).reshape(-1,1)

    kinds = atoms.get_array('spacegroup_kinds')
    kind_idxs = np.argsort(kinds)
    sorted_kinds = kinds[kind_idxs]
    return np.split(kind_idxs, np.where(np.diff(sorted_kinds))[0] + 1)
