import time

def clean_code_block(code_block):
    code_block = code_block.strip()
    if code_block.startswith("```"):
        code_block = code_block[3:]
    if code_block.endswith("```"):
        code_block = code_block[:-3]
    code_block = code_block.strip()
    return code_block

def retry(times, exceptions, sleep=.1):
    """
    Retry Decorator
    Retries the wrapped function/method `times` times if the exceptions listed
    in ``exceptions`` are thrown
    :param times: The number of times to repeat the wrapped function/method
    :type times: Int
    :param Exceptions: Lists of exceptions that trigger a retry attempt
    :type Exceptions: Tuple of Exceptions
    """
    def decorator(func):
        def newfn(*args, **kwargs):
            attempt = 0
            while attempt < times:
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    print(
                        'Exception thrown when attempting to run %s, attempt '
                        '%d of %d' % (func, attempt, times)
                    )
                    attempt += 1
                    time.sleep(sleep)
            return func(*args, **kwargs)
        return newfn
    return decorator

valid_extensions = ('.js', '.jsx', '.py', '.json', '.html', '.css', '.scss', '.yml', '.yaml', '.ts', '.tsx', '.ipynb', '.sh', '.txt', '.md')
directory_blacklist = ('build', 'dist', 'tests', 'log', 'logs', 'docker', 'node_modules', 'venv', 'env', 'assets', 'include', 'docs', 'examples', 'test',)

def filter_path(path):
    filename = path.split('/')[-1]
    if not filename.endswith(valid_extensions):
        return False

    # Ignore any directory with beginning with a dot. Directory may be anywhere in the path
    if any([folder.startswith('.') for folder in path.split('/')]):
        return False

    # Ignore any directory in the blacklist
    if any([blacklisted == path for blacklisted in directory_blacklist]):
        return False

    return True