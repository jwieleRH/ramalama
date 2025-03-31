#!/usr/bin/env bats

load helpers

# bats test_tags=distro-integration
@test "ramalama rag" {
    skip_if_nocontainer
    run_ramalama 22 rag bogus quay.io/ramalama/myrag:1.2
    is "$output" "Error: bogus does not exist" "Expected failure"

    run_ramalama rag README.md https://github.com/containers/ramalama/blob/main/README.md https://github.com/containers/podman/blob/main/README.md quay.io/ramalama/myrag:1.2
    run_ramalama info
    engine=$(echo "$output" | jq --raw-output '.Engine.Name')
    run ${engine} rmi quay.io/ramalama/myrag:1.2
}

# vim: filetype=sh
