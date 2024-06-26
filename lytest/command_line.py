""" Store new references from command line
"""

import os
import argparse
from lytest import __version__, store_reference, ipc_load
from lytest.kdb_xor import run_xor, GeometryDifference
import importlib.util
import subprocess
import textwrap

_loaded_modules = {}


def load_attribute_fromfile(filename, attr):
    # Import the module from the source of that file, then get an attribute
    modulename = os.path.splitext(os.path.basename(filename))[0]
    global _loaded_modules
    if modulename not in _loaded_modules:
        spec = importlib.util.spec_from_file_location(modulename, filename)
        the_module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(the_module)
        except Exception as err:
            raise ImportError(f"Error loading {str(filename)}")
        _loaded_modules[modulename] = the_module
    the_module = _loaded_modules[modulename]
    return getattr(the_module, attr)


top_parser = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description=textwrap.dedent(
        """\
        Available commands are
          store: store a new reference layout
          diff: XOR two files
          run: run one XOR test
          git-config: one time setup for git system

        Type "lytest <command> -h" for help on specific commands
        """
    ),
)
top_parser.add_argument(
    "command",
    type=str,
    choices=["store", "diff", "run", "git-config", "git-diff"],
    metavar="<command>",
)
top_parser.add_argument("args", nargs=argparse.REMAINDER)
top_parser.add_argument(
    "-v", "--version", action="version", version=f"%(prog)s v{__version__}"
)


def cm_main():
    args = top_parser.parse_args()
    if args.command == "store":
        cm_store_ref(args.args)
    elif args.command == "run":
        cm_xor_test(args.args)
    elif args.command == "diff":
        cm_diff(args.args)
    elif args.command == "git-config":
        cm_gitconfig(args.args)
    elif args.command == "git-diff":
        cm_gitdiff(args.args)


store_parser = argparse.ArgumentParser(
    prog="lytest store", description="Store new reference layout"
)
store_parser.add_argument(
    "testfile",
    type=argparse.FileType("r"),
    help="the file in which the container resides",
)
store_parser.add_argument("testname", type=str, help="name of the container")


def cm_store_ref(args):
    store_args = store_parser.parse_args(args)
    test_function = load_attribute_fromfile(
        store_args.testfile.name, store_args.testname
    )
    store_reference(test_function)
    print("Success")


run_parser = argparse.ArgumentParser(prog="lytest run", description="Run one XOR test")
run_parser.add_argument(
    "testfile",
    type=argparse.FileType("r"),
    help="the file in which the container resides",
)
run_parser.add_argument("testname", type=str, help="name of the container")


def cm_xor_test(args):
    run_args = run_parser.parse_args(args)
    # make sure we get the difftest_it kind
    func_name = run_args.testname
    if not func_name.startswith("test_") and not func_name.endswith("_test"):
        for func_name_try in [f"test_{func_name}", f"{func_name}_test"]:
            try:
                load_attribute_fromfile(run_args.testfile.name, func_name_try)
                break
            except AttributeError:
                pass
        else:
            raise AttributeError("No pytest-able version of this attribute was found")
        func_name = func_name_try

    difftesting_function = load_attribute_fromfile(run_args.testfile.name, func_name)
    difftesting_function()
    print("Success")


# File based diff
filebased_parser = argparse.ArgumentParser(
    prog="lytest diff", description="file-based diff integrated with klayout"
)
filebased_parser.add_argument(
    "lyfile1", type=argparse.FileType("r"), help="First layout file (GDS or OAS)"
)
filebased_parser.add_argument(
    "lyfile2", type=argparse.FileType("r"), help="Second layout file (GDS or OAS)"
)
filebased_parser.add_argument(
    "tolerance",
    type=int,
    nargs="?",
    default=1,
    help="Tolerance in database units (usually nanometers)",
)


def cm_diff(args):
    diff_args = filebased_parser.parse_args(args)
    for file in [diff_args.lyfile1, diff_args.lyfile2]:
        file_ext = os.path.splitext(file.name)[1]
        if file_ext.lower() not in [".gds", ".oas", ".kicad_pcb"]:
            raise ValueError(f"Unrecognized layout format: {file.name}")
    ref_file = diff_args.lyfile1.name
    test_file = diff_args.lyfile2.name
    try:
        run_xor(ref_file, test_file, tolerance=diff_args.tolerance, verbose=False)
    except GeometryDifference:
        print("These layouts are different.")
        ipc_load(ref_file, mode=1)
        ipc_load(test_file, mode=2)


# git integration.
# This is not meant to be called by command line users. It gets called by the inner workings of git
git_parser = argparse.ArgumentParser(
    prog="lytest git-diff", description="file-based diff integrated with klayout"
)
git_parser.add_argument("path")
git_parser.add_argument(
    "lyfile1", type=argparse.FileType("r"), help="First layout file (GDS or OAS)"
)
git_parser.add_argument("hash1")
git_parser.add_argument("mode1")
git_parser.add_argument(
    "lyfile2", type=argparse.FileType("r"), help="Second layout file (GDS or OAS)"
)
git_parser.add_argument("hash2")
git_parser.add_argument("mode2")
git_parser.add_argument("similarity", nargs="*")


def cm_gitdiff(args):
    """This no longer has an entry point"""
    git_args = git_parser.parse_args(args)
    if len(git_args.similarity) > 0:
        print("Refusing to process similar files without the same name")
        print("\n".join(git_args.similarity[1:]))
        return
    for file in [git_args.lyfile1, git_args.lyfile2]:
        if (
                git_args.mode2 is None or file.name == "/dev/null"
        ):  # what is this on windows?
            print(
                f"File {[git_args.lyfile1.name, git_args.lyfile2.name]} does not exist on both commits"
            )

            return
        file_ext = os.path.splitext(file.name)[1]
        if file_ext.lower() not in [".gds", ".oas"]:
            raise ValueError(f"Unrecognized layout format: {file.name}")
    ref_file = git_args.lyfile1.name
    test_file = git_args.lyfile2.name
    try:
        run_xor(ref_file, test_file, tolerance=1, verbose=False)
    except GeometryDifference:
        print("Layouts differ:")
        print("  ", test_file)
        print("  ", ref_file)
        ipc_load(ref_file, mode=1)
        ipc_load(test_file, mode=2)


gitconfig_parser = argparse.ArgumentParser(
    prog="lytest git-config", description="One time setup for git integration"
)
gitconfig_parser.add_argument(
    "--local",
    action="store_true",
    help="Install in local git project instead of global",
)


def cm_gitconfig(args):
    gitconfig_args = gitconfig_parser.parse_args(args)
    config_call = ["git", "config"]
    if not gitconfig_args.local:
        config_call.append("--global")
    diff_config_call = config_call + ["diff.lytest.command", "lytest git-diff"]
    subprocess.check_call(diff_config_call)
    binary_config_call = config_call + ["diff.lytest.binary", "true"]
    subprocess.check_call(binary_config_call)

    attr_file = (
        os.path.join(".git", "info", "attributes")
        if gitconfig_args.local
        else os.path.expanduser("~/.gitattributes")
    )

    with open(attr_file, "a+") as fx:
        for filetype in ("gds", "GDS", "oas", "OAS", "kicad_pcb"):
            fx.write("*.{}  diff=lytest\n".format(filetype))


if __name__ == "__main__":
    cm_main()
