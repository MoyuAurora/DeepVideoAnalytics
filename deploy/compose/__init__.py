"""
Code in this file assumes that it is being run via dvactl and git repo root as current directory
"""
import subprocess
import time
import urllib2
import os
import json
import webbrowser


def generate_multi_gpu_compose(fname, config):
    blocks = []
    worker_specs = config['workers']
    for gpu_id, fraction, env_key, worker_name, in worker_specs:
        if fraction > 0:
            blocks.append(
                file('compose/gpu_block.yaml').read().format(worker_name=worker_name, gpu_id=gpu_id,
                                                                 memory_fraction=fraction, env_key=env_key,
                                                                 env_value=1))
        else:
            blocks.append(
                file('compose/gpu_cpu_block.yaml').read().format(worker_name=worker_name, env_key=env_key, env_value=1))
    with open(fname, 'w') as out:
        out.write(file('compose/gpu_skeleton.yaml').read().format(gpu_workers="\n".join(blocks),
                                                                  global_model_gpu_id=config['global_model_gpu_id'],
                                                                  global_model_memory_fraction=config[
                                                                      'global_model_memory_fraction']))


def load_envs(path):
    return {line.split('=')[0]: line.split('=')[1].strip() for line in file(path)}


def create_custom_env(init_process, init_models, cred_envs):
    envs = {'INIT_PROCESS': init_process, 'INIT_MODELS': init_models}
    envs.update(cred_envs)
    with open('custom.env', 'w') as out:
        out.write(file('default.env').read())
        out.write('\n')
        for k, v in envs.items():
            out.write("{}={}\n".format(k, v))


def start_docker_compose(deployment_type, gpu_count, init_process, init_models, cred_envs):
    print "Checking if docker-compose is available"
    max_minutes = 20
    if deployment_type == 'gpu':
        fname = 'docker-compose-{}-gpus.yaml'.format(gpu_count)
    else:
        fname = 'docker-compose-{}.yaml'.format(deployment_type)
    create_custom_env(init_process, init_models, cred_envs)
    print "Starting deploy/compose/{}".format(fname)
    try:
        # Fixed to dev since deployment directory does not matters for checking if docker-compose exists.
        subprocess.check_call(["docker-compose", '--help'],
                              cwd=os.path.join(os.path.dirname(os.path.curdir), 'deploy/compose/'))
    except:
        raise SystemError("Docker-compose is not available")
    print "Pulling/Refreshing container images, first time it might take a while to download the image"
    try:
        if deployment_type == 'gpu':
            print "Trying to set persistence mode for GPU"
            try:
                subprocess.check_call(["sudo", "nvidia-smi", '-pm', '1'])
            except:
                print "Error could not set persistence mode pleae manually run 'sudo nvidia-smi -pm 1'"
                pass
            subprocess.check_call(["docker", 'pull', 'akshayubhat/dva-auto:gpu'])
        else:
            subprocess.check_call(["docker", 'pull', 'akshayubhat/dva-auto:latest'])
    except:
        raise SystemError("Docker is not running / could not pull akshayubhat/dva-auto:latest image from docker hub")
    print "Trying to launch containers"
    try:
        args = ["docker-compose", '-f', fname, 'up', '-d']
        print " ".join(args)
        compose_process = subprocess.Popen(args, cwd=os.path.join(os.path.dirname(os.path.curdir), 'deploy/compose/'))
    except:
        raise SystemError("Could not start container")
    while max_minutes:
        print "Checking if DVA server is running, waiting for another minute and at most {max_minutes} minutes".format(
            max_minutes=max_minutes)
        try:
            r = urllib2.urlopen("http://localhost:8000")
            if r.getcode() == 200:
                print "Open browser window and go to http://localhost:8000 to access DVA Web UI"
                print 'For windows you might need to replace "localhost" with ip address of docker-machine'
                webbrowser.open("http://localhost:8000")
                webbrowser.open("http://localhost:8888")
                break
        except:
            pass
        time.sleep(60)
        max_minutes -= 1
    compose_process.wait()


def stop_docker_compose(deployment_type, gpu_count, clean=False):
    if clean:
        extra_args = ['-v', ]
    else:
        extra_args = []
    if deployment_type == 'gpu':
        fname = 'docker-compose-{}-gpus.yaml'.format(gpu_count)
    else:
        fname = 'docker-compose-{}.yaml'.format(deployment_type)
    print "Stopping deploy/compose/{}".format(fname)
    try:
        subprocess.check_call(["docker-compose", '-f', fname, 'down'] + extra_args,
                              cwd=os.path.join(os.path.dirname(os.path.curdir),
                                               'deploy/compose'))
    except:
        raise SystemError("Could not stop containers")


def get_auth():
    token = subprocess.check_output(["docker", "exec", "-it", "webserver", "scripts/generate_testing_token.py"]).strip()
    server = 'http://localhost:8000/api/'
    with open('creds.json', 'w') as fh:
        json.dump({'server': server, 'token': token}, fh)
    print "token and server information are stored in creds.json"


def handle_compose_operations(args, mode, gpus, init_process, init_models, cred_envs, gpu_compose_filename, gpu_config):
    if mode == 'gpu':
        generate_multi_gpu_compose(gpu_compose_filename, gpu_config)
    if args.action == 'stop':
        stop_docker_compose(mode, gpus)
    elif args.action == 'start':
        start_docker_compose(mode, gpus, init_process, init_models, cred_envs)
        get_auth()
    elif args.action == 'auth':
        get_auth()
    elif args.action == 'clean':
        stop_docker_compose(mode, gpus, clean=True)
    elif args.action == 'restart':
        stop_docker_compose(mode, gpus)
        start_docker_compose(mode, gpus, init_process, init_models, cred_envs)
    else:
        raise NotImplementedError("{} and {}".format(args.action, mode))
