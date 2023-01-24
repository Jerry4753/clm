import json
import sys
import os
import shutil
import humaneval_command

HUMANEVAL_DIR = os.path.abspath(__file__)[: os.path.abspath(__file__).rindex('/') + 1]
sys.path.append(HUMANEVAL_DIR + '../codegen/')
sys.path.append(HUMANEVAL_DIR + '../codet5/')
sys.path.append(HUMANEVAL_DIR + '../plbart/')
sys.path.append(HUMANEVAL_DIR + '../incoder/')
sys.path.append(HUMANEVAL_DIR + '../codex/')

from quixbugs_codegen import codegen_output_to_patch
from quixbugs_codet5 import codet5_output_to_patch
from quixbugs_plbart import plbart_output_to_patch
from quixbugs_incoder import incoder_output_to_patch
from quixbugs_codex import codex_output_to_patch


def insert_fix(filename, start_line, end_line, patch):
    """
    end_row is included in the buggy lines / buggy function
    """
    with open(filename, 'r') as file:
        data = file.readlines()

    with open(filename, 'w') as file:
        for i in range(start_line - 1):
            file.write(data[i] + '\n')
        file.write(patch.strip())
        for i in range(end_line, len(data)):
            file.write(data[i])


def validate_humaneval(input_file, output_file, tmp_dir):
    plausible, total = 0, 0

    humaneval_command.command_with_timeout(['rm', '-rf', tmp_dir + 'src/main/java/humaneval/buggy/'])
    humaneval_command.command_with_timeout(['mkdir', tmp_dir + 'src/main/java/humaneval/buggy/'])
    humaneval_command.command_with_timeout(['rm', '-rf', tmp_dir + 'src/test/java/humaneval/'])
    humaneval_command.command_with_timeout(['mkdir', tmp_dir + 'src/test/java/humaneval/'])

    model_output = json.load(open(input_file, 'r'))
    validated_result = {'config': model_output['config'], 'data': {}}
    # validated_result = json.load(open(output_file, 'r'))
    for proj in model_output['data']:
        if proj in validated_result['data']:
            continue
        if 'output' not in model_output['data'][proj]:
            continue

        print('start validating', proj)
        total += 1

        humaneval_command.command_with_timeout(['rm', '-rf', tmp_dir + 'src/main/java/humaneval/buggy/*.java'])
        humaneval_command.command_with_timeout(['rm', '-rf', tmp_dir + 'src/test/java/humaneval/*.java'])
        shutil.copyfile(tmp_dir + 'src_bak/main/java/humaneval/buggy/' + proj + '.java', tmp_dir + 'src/main/java/humaneval/buggy/' + proj + '.java')
        shutil.copyfile(tmp_dir + 'src_bak/test/java/humaneval/TEST_' + proj + '.java', tmp_dir + 'src/test/java/humaneval/TEST_' + proj + '.java')
        
        validated_result['data'][proj] = {}
        for key, value in model_output['data'][proj].items():
            if key != 'output':
                validated_result['data'][proj][key] = value
        validated_result['data'][proj]['output'] = []
        
        try:
            start_line, end_line = validated_result['data'][proj]['loc'].split('-')
            end_line = str(int(end_line) - 1) if end_line != start_line else end_line
            function_start_line, function_end_line = validated_result['data'][proj]['function range'].split('-')
            function_start_line, function_end_line = function_start_line.split(',')[0], function_end_line.split(',')[0]
        except Exception as e:
            continue

        current_is_correct = False
        for rank, patch in enumerate(model_output['data'][proj]['output']):
            filename = tmp_dir + 'src/main/java/humaneval/buggy/' + proj + '.java'
            if 'CODET5' in model_output['config']:
                patch = codet5_output_to_patch(patch, model_output['config'])
                if model_output['config']  in ['CODET5_BASE_CODEFORM_MASKFORM_NOCOMMENT', 'CODET5_BASE_CODEFORM_COMMENTFORM_NOCOMMENT']:
                    insert_fix(filename, int(start_line), int(end_line), patch)
            elif 'CODEGEN' in model_output['config']:
                patch = codegen_output_to_patch(patch, model_output['config'])
                insert_fix(filename, int(function_start_line), int(function_end_line), patch)
            elif 'PLBART' in model_output['config']:
                patch = plbart_output_to_patch(patch, model_output['config'])
                insert_fix(filename, int(function_start_line), int(function_end_line), patch)
            elif 'INCODER' in model_output['config']:
                patch = incoder_output_to_patch(patch, model_output['config'])
                insert_fix(filename, int(function_start_line), int(function_end_line), patch)
            else:
                assert False, 'unrecognized model.'
            
            correctness = humaneval_command.humaneval_test_suite(proj, tmp_dir)
            if correctness == 'plausible':
                if not current_is_correct:
                    plausible += 1
                    current_is_correct = True
                print(plausible, total, rank, "Plausible patch:", patch)
            elif correctness == 'wrong':
                print(plausible, total, rank, "Wrong patch:", patch)
            elif correctness == 'timeout':
                print(plausible, total, rank, "Timeout patch:", patch)
            elif correctness == 'uncompilable':
                print(plausible, total, rank, "Uncompilable patch:", patch)
            validated_result['data'][proj]['output'].append({
                'patch': patch, 'correctness': correctness
            })
            shutil.copyfile(tmp_dir + 'src_bak/main/java/humaneval/buggy/' + proj + '.java',
                            tmp_dir + 'src/main/java/humaneval/buggy/' + proj + '.java')
        json.dump(validated_result, open(output_file, 'w'), indent=2)

if __name__ == '__main__':
    input_file = sys.argv[1]    # output.json containing the generated patches
    output_file = sys.argv[2]   # validation.json containing the validated result
    tmp_dir = sys.argv[3]       # directory of HumanEval benchmark, default ../../tmp_benchmarks/HumanEval/
    
    validate_humaneval(input_file, output_file, tmp_dir)
