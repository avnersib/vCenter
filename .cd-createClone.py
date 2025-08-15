pipeline {
    agent any

        parameters {
        string(
            name: 'ENVIRONMENT',
            defaultValue: 'dev',
            description: 'Enter the environment'
        )
    }

    stages {
        stage('Run Python Script') {
            steps {
                withCredentials([
                string(credentialsId: 'userName', variable: 'username'),
                string(credentialsId: 'password', variable: 'password')
                ]) {
                sh '''
                python3 createClone.py --username "$username" --password "$password" --env "${params.ENVIRONMENT}"
                '''
                }
            }
        }
    }
}
