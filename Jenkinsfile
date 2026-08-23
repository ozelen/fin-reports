// Jenkins credential ID must be `ozelen` (SSH Username with private key, username ozelen).
// Store the key in Jenkins only (global credentials domain). Do not put a private key in this repo.
pipeline {
  agent any
  parameters {
    string(name: 'IMAGE_TAG', defaultValue: 'latest', description: 'Image tag from GitHub Actions (git SHA)')
  }
  environment {
    IMAGE_TAG = "${params.IMAGE_TAG}"
  }
  stages {
    stage('Deploy') {
      steps {
        withCredentials([sshUserPrivateKey(credentialsId: 'ozelen', keyFileVariable: 'SSH_KEY', usernameVariable: 'SSH_USER')]) {
          sh '''
            set -eu
            TAG="${IMAGE_TAG:?IMAGE_TAG required}"

            ssh -i "$SSH_KEY" -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new \
              "${SSH_USER}@192.168.1.185" "bash -s -- ${TAG}" <<'REMOTE'
            set -eu
            K="sudo k3s kubectl"
            TAG="${1:?IMAGE_TAG required}"

            redeploy() {
              ns="$1"
              image="$2"
              if ! $K get ns "$ns" >/dev/null 2>&1; then
                echo "skip missing namespace $ns"
                return 0
              fi
              deploys="$($K -n "$ns" get deploy -o jsonpath='{.items[*].metadata.name}')"
              if [ -z "$deploys" ]; then
                echo "skip $ns: no deployments"
                return 0
              fi
              for deploy in $deploys; do
                container="$($K -n "$ns" get deploy "$deploy" -o jsonpath='{.spec.template.spec.containers[0].name}')"
                echo "set $ns/$deploy $container=$image:$TAG"
                $K -n "$ns" set image "deploy/$deploy" "$container=$image:$TAG"
                $K -n "$ns" rollout status "deploy/$deploy" --timeout=180s
              done
            }

            redeploy ix-income-share-api zelenuk/income-share-api
            redeploy ix-income-share-bot zelenuk/income-share-bot
REMOTE
          '''
        }
      }
    }
  }
}
