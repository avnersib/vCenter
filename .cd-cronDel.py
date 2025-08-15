pipeline {
    agent any

    stages {
        stage('Run Python Script') {
            steps {
                withCredentials([
                string(credentialsId: 'userName', variable: 'username'),
                string(credentialsId: 'password', variable: 'password')
                ]) {
                sh '''
                python3 cronDel.py --username "$username" --password "$password"
                '''
                }
            }
        }
    }
}
