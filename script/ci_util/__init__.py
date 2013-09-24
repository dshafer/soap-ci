import os
import yaml
import subprocess
import shlex
import traceback
import re

macro_re = re.compile('\$\{(\w+)\}')
def shell_source(script, **kwargs):
    print 'sourcing {0}'.format(script)
    if not os.path.exists(script):
        print '  error: script does not exist!'
        return 1
    pipe = subprocess.Popen(". {0}; env".format(script), stdout=subprocess.PIPE, shell=True, **kwargs)
    output = pipe.communicate()[0]
    env = dict((line.split("=", 1) for line in output.splitlines()))
    os.environ.update(env)

def expand_macro(macro, names):
    result = macro
    match = macro_re.search(result)
    while match:
        name = match.groups()[0]
        if not name in names:
            raise Exception('Error: found undefined name "{0}" in "{1}".  Known names are: {2}'.format(name, macro, names)) 
        val = names[name]
        result = result[:match.start()] + str(val) + result[match.end():]
        match = macro_re.search(result)

    return result
    
def run_cmd(cmd, **kwargs):
    if cmd.startswith('source ') or cmd.startswith('. '):
        cmd = ' '.join(cmd.split(' ')[1:])
        return shell_source(cmd)
    else:
        print('running {0}'.format(cmd))
        return subprocess.call(shlex.split(cmd), **kwargs)

def run_and_capture_output(cmd, **kwargs):
    proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    (stdout, stderr) = proc.communicate()
    return (proc.returncode, stdout, stderr)

class Sandbox(object):
    def __init__(self, config, sandbox_dict):
        self.config = config
        self.name = sandbox_dict['name']
        self.create_macro = sandbox_dict['create_cmd']
        self.enter_macro = sandbox_dict['enter_cmd']
    
    def create(self, names):
        cmd = expand_macro(self.create_macro, names)
        if run_cmd(cmd):
            raise Exception('Failed to create sandbox')

    def enter(self, names):
        if hasattr(self.enter_macro, '__iter__'):
            print 'running command sequence'
            for enter_macro in self.enter_macro:
                cmd = expand_macro(enter_macro, names)
                if run_cmd(cmd):
                    raise Exception('Failed to enter sandbox')
        else:
            cmd = expand_macro(self.enter_macro, names)
            if run_cmd(cmd):
                raise Exception('Failed to enter sandbox')


class Repo(object):
    def __init__(self, config, repo_dict):
        self.config = config
        self.name = repo_dict['name']
        self.working_dir = os.path.join(config.working_dir, 'repos', self.name)
        self.checkout_dir = os.path.join(self.working_dir, repo_dict.get('checkout_dir', '.repo_mirror'))
        self.url = repo_dict['url']
        self.branch_dir = os.path.join(self.working_dir, 'branches')
        self.default_build = repo_dict['default_build']
        if repo_dict.get('sandbox_type'):
            self.sandbox = config.sandboxes[repo_dict['sandbox_type']]
        else:
            self.sandbox = None

        self.pre_test_cmd = repo_dict.get('pre_test_cmd')

        self.macro_names = dict(config.macro_names)
        self.macro_names.update(repo_dict)
        self.macro_names['__repo_name__'] = self.name

        self.ci_branches = {}
        for ci_branch_dict in repo_dict['ci_branches']:
            ci_branch = CiBranch(self, ci_branch_dict)
            self.ci_branches[ci_branch.name] = ci_branch

    def clone_if_necessary(self):
        if not os.path.exists(self.working_dir):
            os.makedirs(self.working_dir)
        if not os.path.exists(self.branch_dir):
            os.makedirs(self.branch_dir)
        if not os.path.exists(self.checkout_dir):
            git_clone_cmd = 'git clone --no-checkout {0} {1}'.format(self.url, self.checkout_dir)
        if not os.path.exists(os.path.join(self.checkout_dir, '.git')):
            if 0 != subprocess.call(shlex.split(git_clone_cmd)):
                raise Exception('Failed to clone repository {0}'.format(self.url) + traceback.format_exc)

    def fetch(self):
        git_cmd = shlex.split('git fetch origin')
        subprocess.call(git_cmd, cwd=self.checkout_dir)

class Build(object):
    def __init__(self, ci_branch, build_dict):
        self.ci_branch = ci_branch
        self.steps = {}
        self.steps['setup'] = build_dict.get('setup', [])
        self.steps['teardown'] = build_dict.get('teardown', [])
        self.steps['build_cmd'] = build_dict.get('build_cmd', [])
        self.success = build_dict.get('success', [])
        self.failure = build_dict.get('failure', [])

    def _run_stage(self, command_list, stdout_prev = '', stderr_prev = ''):
        stdout = stdout_prev
        stderr = stderr_prev
        for cmd_macro in command_list:
            cmd = expand_macro(cmd_macro, self.ci_branch.macro_names)
            (returncode, _stdout, _stderr) = run_and_capture_output(cmd, cwd=self.ci_branch.working_dir)
            stdout = stdout + _stdout
            stderr = stderr + _stderr
            if returncode:
                return (False, stdout, stderr)
        return (True, stdout, stderr)

    def execute(self, sha):
        output_dir = os.path.join(self.ci_branch.repo.config.output_dir, self.ci_branch.repo.name, self.ci_branch.safe_branch_name, sha) 
        stdout, stderr = '',''
        for step in ('setup', 'build_cmd', 'teardown'):
            (success, stdout, stderr) = self._run_stage(self.steps[step], stdout, stderr)
            if not success:
                self.record_failure(output_dir, step, stdout, stderr)
                return False

        self.record_success(output_dir, stdout, stderr)
        return success, stdout, stderr
    
    def record_result(self, output_dir, status_png, log):
        try:
            os.makedirs(output_dir)
        except Exception:
            pass
        try:
            os.symlink(status_png, os.path.join(output_dir, 'status.png'))
        except Exception:
            pass
        try:
            f = open(os.path.join(output_dir, 'log.txt'), 'w')
            f.write(log)
        except Exception:
            pass
        finally:
            try:
                f.close()
            except Exception:
                pass
        try:
            symlink_path = os.path.join(self.ci_branch.repo.config.output_dir, self.ci_branch.repo.name, self.ci_branch.safe_branch_name, 'current')
            if os.path.exists(symlink_path):
                os.unlink(symlink_path)
            os.symlink(output_dir, symlink_path)
        except Exception:
            pass


    def record_failure(self, output_dir, step, stdout, stderr):
        log = 'Result: FAIL at {0}\n\n'.format(step) + \
              '*********STDOUT**********:\n{0}\n'.format(stdout) + \
              '*********STDERR**********:\n{0}\n'.format(stderr)
        self.record_result(output_dir, self.ci_branch.repo.config.failure_png, log)
        
    def record_success(self, output_dir, stdout, stderr):
        log = 'Result: Success\n\n' + \
              '*********STDOUT**********:\n{0}\n'.format(stdout) + \
              '*********STDERR**********:\n{0}\n'.format(stderr)
        self.record_result(output_dir, self.ci_branch.repo.config.success_png, log)
        

class CiBranch(object):
    def __init__(self, repo, ci_dict):
        self.repo = repo
        self.name = ci_dict['name']
        self.working_dir = os.path.join(self.repo.branch_dir, self.name)
        self.safe_branch_name = self.name.replace('/', '_')
        build_dict = ci_dict.get('build', repo.default_build)

        self.macro_names = dict(repo.macro_names)
        self.macro_names.update(ci_dict)
        self.macro_names['__branch_name__'] = self.name
        self.macro_names['__branch_name_safe__'] = self.safe_branch_name
        self.macro_names['__branch_working_dir__'] = self.working_dir

        self.build = Build(self, build_dict)

    def create_sandbox(self):
        if self.repo.sandbox:
            self.repo.sandbox.create(self.macros)

    def init_sandbox(self):
        if self.repo.sandbox:
            try:
                self.repo.sandbox.enter(self.macro_names)
            except:
                self.repo.sandbox.create(self.macro_names)
                self.repo.sandbox.enter(self.macro_names)

    def _get_hash_filename(self, slot):
        return os.path.join(self.repo.branch_dir, '{0}.{1}'.format(self.name, slot))

    def latest_finished_hash(self):
        filename = self._get_hash_filename('finished')
        if os.path.exists(filename):
            return open(filename, 'r').read().strip()
        else:
            return None
    
    def commit_has_already_been_tested(self, sha):
        latest_finished = self.latest_finished_hash()
        print '{0}.commit_has_already_been_tested({1})\n  finished = ({2})'.format(self.name, sha, latest_finished)
        if not latest_finished:
            return False
        if sha != latest_finished:
            cmd = 'git merge-base --is-ancestor {0} {1}'.format(sha, latest_finished)
            print '{0}: running {1}'.format(self.name, cmd)
            return subprocess.call(shlex.split(cmd), cwd=self.working_dir) == 0
        else:
            print '{0}.commit... - returning True'
            return True

    def enqueue_hash(self, hsh):
        queue_file = open(self._get_hash_filename('queue'), 'a')
        queue_file.write(hsh + '\n')
        queue_file.close()

    def mark_finished(self, sha):
        finished_file = open(self._get_hash_filename('finished'), 'w')
        finished_file.write(sha)
        finished_file.close()

    def latest_remote_hash(self):
        cmd = 'git rev-parse origin/{0}'.format(self.name)
        print ('running {0}'.format(cmd))
        return subprocess.check_output(shlex.split(cmd), cwd=self.repo.checkout_dir).strip()

    def build_in_progress(self):
        return os.path.exists(self._get_hash_filename('testing'))

    def _get_next_sha(self):
        queue_file = open(self._get_hash_filename('queue'), 'r')
        line = queue_file.readline()
        while line:
            sha = line.strip()
            print('{0}._get_next_sha - considering {1}'.format(self.name, sha))
            if not self.commit_has_already_been_tested(sha):
                return sha
            line = queue_file.readline()
        return None

    def run_build_queue(self):
        print('{0} : run_build_queue'.format(self.name))
        try:
            # touch the branch .testing file to mark the queue as running
            open(self._get_hash_filename('testing'), 'a').close()
            
            sha = self._get_next_sha()
            print '{0} sha is {1}'.format(self.name, sha)
            while sha:
                try:
                    self.update_to_commit(sha)
                    (success, stdout, stderr) = self.build.execute(sha)
                    print ('{0} : {1}\nSTDOUT:\n{2}\nSTDERR:\n{3}'.format(self.name, success, stdout, stderr))
                finally:
                    self.mark_finished(sha)
                sha = self._get_next_sha()

        finally:
            print('cleaning up {0}'.format(self.name))
            os.unlink(self._get_hash_filename('queue'))
            os.unlink(self._get_hash_filename('testing'))


    def update_to_commit(self, sha):
        cmd = 'git merge --ff-only {0}'.format(sha)
        print('updating {0} to {1}'.format(self.name, sha))
        subprocess.call(shlex.split(cmd), cwd=self.working_dir)

        if self.repo.pre_test_cmd:
            run_cmd(expand_macro(self.repo.pre_test_cmd, self.macro_names), cwd=self.working_dir )

    def do_test(self):
        print 'building {0}'.format(self.name)
        
        stdout = ''
        stderr = ''
        for cmd_macro in self.test:
            cmd = expand_macro(cmd_macro, self.macro_names)
            (returncode, _stdout, _stderr) = run_and_capture_output(cmd, cwd=self.working_dir)
            stdout = stdout + _stdout
            stderr = stderr + _stderr
            if returncode:
                return (False, stdout, stderr)
        return (True, stdout, stderr)
        

class Config(object):
    def __init__(self, **kwargs):
        self.working_dir = kwargs.pop('working_dir', '')
        self.output_dir = kwargs.pop('output_dir', os.path.join(self.working_dir, 'results'))


        config_file_name = kwargs.pop('config_file_name', 'config.yaml')

        yaml_dict = yaml.load(open(os.path.join(self.working_dir, config_file_name)))

        self.macro_names = yaml_dict.get('define', {})
        self.macro_names['__lib_dir__'] = os.path.dirname(os.path.realpath(__file__))
        
        self.success_png = expand_macro(yaml_dict.get('success_png', '${__lib_dir__}/assets/Thumbs-up-icon.png'), self.macro_names)
        self.failure_png = expand_macro(yaml_dict.get('failure_png', '${__lib_dir__}/assets/Thumbs-down-icon.png'), self.macro_names)

        self.sandboxes = {}
        for sandbox_dict in yaml_dict['sandbox_types']:
            sandbox = Sandbox(self, sandbox_dict)
            self.sandboxes[sandbox.name] = sandbox

        self.repos = {}
        for repo_dict in yaml_dict['repos']:
            repo = Repo(self, repo_dict)
            self.repos[repo.name] = repo
