"""
Version information for the node-client.
This file is auto-updated during the build process.
"""

VERSION = "1.0.11"
VERSION_DATE = "2026-02-12"

# Per confronto versioni
def parse_version(version_str):
    """Parse version string to tuple for comparison."""
    try:
        parts = version_str.split('.')
        return tuple(int(p) for p in parts)
    except:
        return (0, 0, 0)

def is_newer(remote_version, local_version=VERSION):
    """Check if remote version is newer than local."""
    return parse_version(remote_version) > parse_version(local_version)
