pipeline {
    agent any

    stages {
        stage('Run Python Script') {
            steps {
                // Replace script.py with your Python file
                sh 'python3 cronDel.py'
            }
        }
    }
}
