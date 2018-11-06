def python_versions = [
    "3.5.3", "3.5.4", "3.5.5",
    "3.6.0", "3.6.1", "3.6.2", "3.6.3", "3.6.4", "3.6.5",
]

def the_steps = python_versions.collectEntries {
    ["Python $it": run_ci(it)]
}

def run_ci(python_version) {
    return {
        timestamps {
            docker.image("python:${python_version}").inside {
                checkout scm
                sh 'make install'
                sh 'make test'
            }
        }
    }
}

pipeline {
    agent none
    environment {
        GIT_COMMITTER_NAME  = 'Joe Doe'
        GIT_COMMITTER_EMAIL = 'joe.doe@example.com'
        HOME                = '/tmp/'
    }
    stages {
        stage('Parallel Stage') {
            steps {
                script {
                    parallel(the_steps)
                }
            }
        }
    }
}
