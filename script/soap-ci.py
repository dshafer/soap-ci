import argparse
import os
import sys
import ci_util
import subprocess
import shlex


def main(args_array):
    script_dir = os.path.dirname(os.path.realpath(__file__))

    parser = argparse.ArgumentParser(description="SOAP-CI manager script")
    parser.add_argument('-w', '--working-dir')

    args = parser.parse_args(args_array)
    working_dir = os.path.abspath(args.working_dir)

    config = ci_util.Config(working_dir=working_dir)

    # iterate through all of the repos.  Fetch latest changes for each one,
    # and kick off the individual repo script

    for repo_name, repo in config.repos.iteritems():
        repo.clone_if_necessary()

        repo_cmd = 'python soap-ci-repo.py --working-dir={0} --repo={1}'.format(working_dir, repo.name)
        repo_proc = subprocess.Popen(shlex.split(repo_cmd), cwd=script_dir)
        

        

if __name__ == '__main__':
    status = main(sys.argv[1:])
    sys.exit(status)
