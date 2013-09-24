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
    parser.add_argument('--branch')

    args = parser.parse_args(args_array)
    working_dir = os.path.abspath(args.working_dir)

    config = ci_util.Config(working_dir=working_dir)

    repo = config.repos[args.repo]
    repo.expand_branch_wildcards()
    ci_branch = repo.ci_branches[args.branch]

    #check out the branch locally if necessary
    if not os.path.exists(ci_branch.working_dir):
        checkout_cmd = './git-new-workdir {0} {1} {2}'.format(repo.checkout_dir, ci_branch.working_dir, ci_branch.name)
        print('running {0}'.format(checkout_cmd))
        checkout_proc = subprocess.call(shlex.split(checkout_cmd), cwd=script_dir)

    ci_branch.init_sandbox()


    latest_remote_hash = ci_branch.latest_remote_hash()
    print('latest hash for branch {0} is {1}'.format(ci_branch.name, latest_remote_hash))
    ci_branch.enqueue_hash(latest_remote_hash)

    if not ci_branch.build_in_progress():
        ci_branch.run_build_queue()

    print('{0} {1} - exiting'.format(ci_branch.name, __file__))
        

if __name__ == '__main__':
    status = main(sys.argv[1:])
    sys.exit(status)
