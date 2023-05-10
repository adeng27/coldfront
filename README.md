# MyBRC/MyLRC User Portal

[![Documentation Status](https://readthedocs.org/projects/coldfront/badge/?version=latest)](https://coldfront.readthedocs.io/en/latest/?badge=latest)

The MyBRC User Portal is an access management system for UC Berkeley Research
IT's Berkeley Research Computing program. It enables users to create or join
projects, gain access to the clusters managed by BRC, view the statuses of
their requests and access, view their allocation quotas and usages, and update
personal information. It enables administrators to handle these requests and
manage users and projects. The portal is built on top of ColdFront.

The MyLRC User Portal is an upcoming second instance of the same system,
developed for Lawrence Berkeley National Laboratory's Laboratory Research
Computing program.

ColdFront is an open source resource allocation system designed to provide a
central portal for administration, reporting, and measuring scientific impact
of HPC resources. ColdFront was created to help HPC centers manage access to a
diverse set of resources across large groups of users and provide a rich set of
extensible meta data for comprehensive reporting. ColdFront is written in
Python and released under the GPLv3 license.

## Vagrant VM Install (Recommended)

The application may be installed within a Vagrant VM that is running on
Scientific Linux 7. The VM is provisioned using the same Ansible playbook
used in production.

1. Install [VirtualBox](https://www.virtualbox.org/).
2. Clone the repository.
   ```
   git clone https://github.com/ucb-rit/coldfront.git
   cd coldfront
   ```
3. Prevent Git from detecting changes to file permissions.
   ```
   git config core.fileMode false
   ```
4. Checkout the desired branch (probably `develop`).
5. Install vagrant-vbguest.
   ```
   vagrant plugin install vagrant-vbguest
   ```
6. Create a `main.yml` file in the top-level of the repository. This is a file
of variables used by Ansible to configure the system.
   ```
   cp bootstrap/ansible/main.copyme main.yml
   ```
7. Customize `main.yml`. In particular, uncomment everything under the `dev_settings` section, and fill in the below variables. Note
that quotes need not be provided, except in the list variable.
   ```
   db_admin_passwd: password_here
   redis_passwd: password_here
   from_email: you@email.com
   admin_email: you@email.com
   email_admin_list: ["you@email.com"]
   request_approval_cc_list: ["you@email.com"]
   ```
8. Provision the VM. This should run the Ansible playbook. Expect this to take
a few minutes on the first run.
   ```
   vagrant up
   ```
9. SSH into the VM.
   ```
   vagrant ssh
   ```
10. On the host machine, navigate to `http://localhost:8880`, where the
application should be served.
11. (Optional) Load data from a database dump file.
    ```
    # Clear the Django database to avoid conflicts.
    python manage.py sqlflush | python manage.py dbshell
    # Load from the dump file (use the -k option if the command errors because database is being accessed).
    sh bootstrap/development/load_database_backup.sh [-k] DB_NAME /absolute/path/to/dump.file
    # Set user passwords.
    python manage.py set_passwords --password <password>
    ```

### Miscellanea

#### Virtual Machine

- Once the VM has been provisioned the first time, starting and accessing it 
can be done with:
  ```
  vagrant up
  vagrant ssh
  ```

- To stop the VM, run:
  ```
  vagrant halt
  ```

- To re-provision the VM, run:
  ```
  vagrant provision
  ```

#### Environment

- The application is served via Apache, so any changes to the application
(excluding changes to templates) are not applied until Apache is restarted,
which can be done with:
  ```
  sudo service httpd restart
  ```
- The Ansible playbook can be run manually as follows.
  ```
  cd /vagrant/coldfront_app/coldfront
  # Assert that there is a properly-configured main.yml in the current directory.
  ansible-playbook bootstrap/ansible/playbook.yml
  ```
  - Note that to skip initial provisioning tasks you can use the
`--tags common` or `--skip-tags provisioning` arguments to `ansible-playbook`:
  - Alternatively, you can set `provisioning_tasks` to `False` in `main.yml`

- Any custom Django settings can be applied by modifying `dev_settings.py`.
Note that running the Ansible playbook will overwrite these.

#### Emails

- By default, emails are configured to be sent via SMTP on port 1025. If no
such server is running on that port, many operations will fail. To start a
server, start a separate SSH session (`vagrant ssh`), and run the below. All
emails will be outputted here for inspection.
  ```
  python -m smtpd -n -c DebuggingServer localhost:1025
  ```

#### pylint

- [pylint](https://pylint.pycqa.org/en/latest/) is a python module that tests 
code for style and helps enforce coding standards. The plugin pylint_django 
improves pylint's ability to analyse Django code.

- To run pylint with the pylint_django plugin on a python file, call pylint 
from the command line:
  ```
  pylint <file_path>
  ```
    - pylint must either be called from the same directory as the file `setup.cfg` 
  or you can explicitly define the config file by using the flag `--rcfile=<config_path>`.
    - Note you can also run pylint on each python file in a directory by 
  passing in the directory as <file_path>.
    - For example, to run pylint on all python files in the directory 
  `coldfront/core/statistics/` from a location other than the top level 
  directory, run the following command:
      ```
      pylint --rcfile=/vagrant/coldfront_app/coldfront/setup.cfg coldfront/core/statistics/
      ```
- By default, output is written to stdout. To output to a file, include 
the `--output=<filename>` flag.
  ```
  pylint --output=<filename> <file_path>
  ```

#### coverage

- [coverage](https://coverage.readthedocs.io/en/6.3.2/) is a python module 
that gauges the effectiveness of tests by measuring the code coverage 
of Python programs.

- To run coverage alongside the Django test suite, call coverage from the 
command line:
  ```
  coverage run manage.py test <path.to.tests>
  ```
  - `<path.to.tests>` takes the normal form of calling Django tests. For example, 
to run the tests located in 
  `coldfront/core/statistics/tests`, run the following command:
    ```
    coverage run manage.py test coldfront.core.statistics.tests
    ```

  - `--source` flag limits the code measured to the code within the specified 
location, which can be either files or directories. To specify multiple 
sources, comma separate the paths.

  - `--omit` flag will not measure the coverage of code within files or 
directories specified. Like the source flag above, comma separate 
multiple files or directories to omit.

  - For example, the following command will ignore all migration files and
  only measure code in the statistics directory.
    ```
    coverage run --omit=*/migrations/* --source=coldfront/core/statistics/ manage.py test coldfront.core.statistics.tests
    ```
  
  - After successfully running, a database file `.coverage` is generated 
  that contains the run results.

- To view the results in the command line, run:
  ```
  coverage report
  ```

- To view the report in an annotated HTML format, run:
  ```
  coverage html
  ```
  
    - This generates the directory `htmlcov` and writes the coverage 
  report to `htmlcov/index.html`.
  
    - Open `htmlcov/index.html` in a browser to view which lines of 
  code were covered by the tests and which were not.

## Docker - Quick Install (Recommend)
1. Generate configuration (`dev_settings.py`): have Python with the `jinja2` and `pyyaml` libraries installed, and then run `bootstrap/development/gen_config.sh`
2. Build Images: In the base directory, run `docker build . -t coldfront` and `docker build . -f Dockerfile.db -t coldfront_db`. `--build-arg PORTAL=mylrc` can be added to the build command to build for mylrc.
3. If needed, modify `.env` to customize the web server port and the database name (e.g from `cf_mybrc_db` to `cf_mylrc_db`)
4. To run: In the base directory, run `docker compose up`
5. To enter the coldfront container (similar to `vagrant ssh`): run `docker exec -it coldfront-coldfront-1 bash`
6. To load a database backup: run `bootstrap/development/docker_load_database_backup.sh ${DB_NAME} ${PATH_TO_DUMP}`
7. To start from scratch (delete volumes): In the base directory, run `docker compose down --volumes`

## Local Machine - Quick Install (Not Recommended)

1. ColdFront requires Python 3.6, memcached, and redis.

### CentOS (7)

Install EPEL then install required packages:

```
sudo yum install epel-release
sudo yum install python36 python36-devel memcached redis

# Install SQLite >= 3.8.3 from source since it is absent from the CentOS software repositories
wget https://sqlite.org/2020/sqlite-autoconf-XXXXXXX.tar.gz
tar -xzf sqlite-autoconf-XXXXXXX
cd sqlite-autoconf-XXXXXXX
./configure
make
make install

#Check version
sqlite3 --version
```


### CentOS (8)

Install EPEL then install required packages:

```
sudo yum install epel-release
sudo yum install python36 python36-devel memcached redis
```

### Ubuntu (16.04)
```
sudo add-apt-repository ppa:jonathonf/python-3.6
sudo apt-get update
sudo apt-get install python3.6 python3.6-venv memcached redis-server
```

2. Clone ColdFront in a new directory and create a Python virtual environment for ColdFront
```
mkdir coldfront_app
cd coldfront_app
git clone https://github.com/ubccr/coldfront.git
python3.6 -mvenv venv
```

3. Activate the virtual environment and install the required Python packages
```
source venv/bin/activate
cd coldfront
pip install wheel
pip install -r requirements.txt

```

4. Copy coldfront/config/local_settings.py.sample to coldfront/config/local_settings.py.
```
cp coldfront/config/local_settings.py.sample coldfront/config/local_settings.py
```

5. Copy config/local_strings.py.sample to config/local_strings.py and update if desired.
```
cp coldfront/config/local_strings.py.sample coldfront/config/local_strings.py
```

6. Run initial setup
```
python manage.py initial_setup
```

7. OPTIONAL: Add some test data
```
python manage.py load_test_data
```

8. Start development server
```
python manage.py runserver 0.0.0.0:8000
```

9. Point your browser to http://localhost:8000

You can log in as `admin` with password `test1234`.
You can log in as a PI using username `cgray` with password `test1234`.
You can log in as another PI using username `sfoster` with password `test1234`.

Password for all users is also `test1234`.

### Additional MyBRC/MyLRC Setup Steps

10. Run additional commands for setting up the database.

```
python manage.py add_accounting_defaults
python manage.py create_allocation_periods
python manage.py create_staff_group
```

## Directory structure

- coldfront
    - core - The core ColdFront application
        - field_of_science
        - grant
        - portal
        - project
        - publication
        - resource
        - statistics
        - allocation
        - user
        - utils
    - libs - Helper libraries
    - plugins - Plugins that can be configured in ColdFront
        - freeipa
        - iquota
        - ldap_user_search
        - mokey_oidc
        - slurm
        - system_monitor

## Accessibility

The service should be accessible to people with disabilities.

In practice, when contributing to the code, ensure that changes do not cause
accessibility issues to be flagged by the
[tota11y](https://khan.github.io/tota11y/) tool. This will be considered
during the code review process.

## REST API

The service's REST API is located at `/api`.

### Getting a Token

Some endpoints require an authorization token, which can be retrieved:

1. From an API endpoint, using username and password (not recommended over
HTTP):<br><br>

   Make a `POST` request to `/api/api_token_auth/` with body:

   ```
   {
       "username": "username",
       "password": "password",
   }
   ```

   This will return a response containing the requested user's token. Note that
the token displayed below is not valid.

   ```
   {
       "token": "c99b5142a126796ff03454f475b0381736793a1f"
   }
   ```

2. For developers, from the Django shell:

   ```
   from coldfront.core.user.models import ExpiringToken
   from django.contrib.auth.models import User

   username = "username"
   user = User.objects.get(username=username)
   ExpiringToken.objects.create(user=user)
   ```

### Authorizing a Request

For those endpoints requiring an authorization token, it must be provided in
the request headers. Note that this is exposed when not using HTTPS.

```
{
    "Authorization": "Token c99b5142a126796ff03454f475b0381736793a1f",
}
```

#### cURL Example

```
curl --header "Authorization: Token c99b5142a126796ff03454f475b0381736793a1f" https://domain.tld/api/
```

### Limiting Write Access

Some methods (i.e., `POST`, `PUT`, `PATCH`) may only be accessible to
superusers. For these, the provided authorization token must belong to a user
with `is_superuser` set to `True`.

### Limiting Access by IP

Access to the API may be limited by IP range. This can be configured in
Ansible, via the `ip_range_with_api_access` variable.

## Deployments

Deployments and configuration management are handled by Ansible, located in
the `bootstrap/ansible` directory.

In particular, the Ansible playbook installs, enables, and configures
PostgreSQL and Redis, creates log files, installs Pip requirements, copies
ColdFront settings files, runs initial setup, migrates the database, collects
static files, creates WSGI files for Apache, and restarts Apache.

Note that there are some additional server setup steps that are not currently
captured in the Ansible playbook.

Also note that on production environments you must install necessary Ansible
collections using
`ansible-galaxy collection install -r bootstrap/ansible/requirements.yml`
before initially running the playbook.

1. Create `main.yml`.

```
cp bootstrap/ansible/main.copyme main.yml
```

2. Modify `main.yml` depending on the current deployment.

3. Run the Ansible playbook as the `djangooperator` user defined in `main.yml`.

```
ansible-playbook bootstrap/ansible/playbook.yml
```

### Dynamic Settings

Some configuration may need to be updated without a server restart (e.g., links
to external resources). Such configuration is managed by `django-constance` and
stored in Redis. To update these, navigate to the URL path
`/admin/constance/config/`, and set the correct values for the current
deployment.


## License

ColdFront is released under the GPLv3 license. See the LICENSE file.
