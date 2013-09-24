import argparse
import os
import sys
import ci_util
import subprocess
import shlex
import pprint

def main(args_array):
    script_dir = os.path.dirname(os.path.realpath(__file__))

    parser = argparse.ArgumentParser(description="SOAP-CI Repository script")
    parser.add_argument('-w', '--working-dir')
    parser.add_argument('--repo') 

    args = parser.parse_args(args_array)
    working_dir = os.path.abspath(args.working_dir)

    config = ci_util.Config(working_dir=working_dir)

    repo = config.repos[args.repo]

    repo.fetch()

    for branch_name in repo.ci_branches:
        br_cmd = 'python soap-ci-branch.py --working-dir {0} --repo {1} --branch {2}'.format(working_dir, repo.name, branch_name)
        pr_proc = subprocess.Popen(shlex.split(br_cmd), cwd=script_dir)
        

if __name__ == '__main__':
    status = main(sys.argv[1:])
    sys.exit(status)
