import json
import sys
import os
import shutil
import quixbugs_command

QUIXBUGS_DIR = os.path.abspath(__file__)[: os.path.abspath(__file__).rindex('/') + 1]
sys.path.append(QUIXBUGS_DIR + '../codegen_finetune/')
sys.path.append(QUIXBUGS_DIR + '../codet5_finetune/')
sys.path.append(QUIXBUGS_DIR + '../plbart_finetune/')
sys.path.append(QUIXBUGS_DIR + '../incoder_finetune/')

from quixbugs_codegen_finetune import codegen_output_to_patch
from quixbugs_codet5_finetune import codet5_output_to_patch
from quixbugs_plbart_finetune import plbart_output_to_patch
from quixbugs_incoder_finetune import incoder_output_to_patch


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


def validate_quixbugs(input_file, output_file, tmp_dir):
    plausible, total = 0, 0

    if not os.path.exists(tmp_dir):
        quixbugs_command.command_with_timeout(['mkdir', tmp_dir])

    model_output = json.load(open(input_file, 'r'))
    validated_result = {'config': model_output['config'], 'data': {}}
    for proj in model_output['data']:
        print('start validating', proj)
        total += 1
        quixbugs_command.command_with_timeout(['rm', '-rf', tmp_dir + '/java_programs/'])
        quixbugs_command.command_with_timeout(['mkdir', tmp_dir + '/java_programs/'])

        shutil.copyfile(tmp_dir + "/java_programs_bak/" + proj + '.java',
                        tmp_dir + "/java_programs/" + proj + '.java')
        shutil.copyfile(tmp_dir + "/java_programs_bak/Node.java", tmp_dir + "/java_programs/Node.java")
        shutil.copyfile(tmp_dir + "/java_programs_bak/WeightedEdge.java", tmp_dir + "/java_programs/WeightedEdge.java")

        validated_result['data'][proj] = {}
        for key, value in model_output['data'][proj].items():
            if key != 'output':
                validated_result['data'][proj][key] = value
        validated_result['data'][proj]['output'] = []
        start_line, end_line = validated_result['data'][proj]['loc'].split('-')
        end_line = str(int(end_line) - 1) if end_line != start_line else end_line
        current_is_correct = False
        for rank, patch in enumerate(model_output['data'][proj]['output']):
            filename = tmp_dir + "/java_programs/" + proj + '.java'
            if 'codet5' in input_file:
                patch = codet5_output_to_patch(patch)
                insert_fix(filename, int(start_line), int(end_line), patch)
            elif 'codegen' in input_file:
                patch = codegen_output_to_patch(patch)
                insert_fix(filename, int(start_line), int(end_line), patch)
            elif 'plbart' in input_file:
                patch = plbart_output_to_patch(patch)
                insert_fix(filename, int(start_line), int(end_line), patch)
            elif 'incoder' in input_file:
                patch = incoder_output_to_patch(patch)
                insert_fix(filename, int(start_line), int(end_line), patch)
            else:
                assert False, 'unrecognized model.'
            
            compile = quixbugs_command.compile_fix(filename, tmp_dir + "/java_programs/")
            correctness = 'uncompilable'
            if compile:
                correctness = quixbugs_command.quixbugs_test_suite(proj, quixbugs_dir=tmp_dir)
                if correctness == 'plausible':
                    if not current_is_correct:
                        plausible += 1
                        current_is_correct = True
                    print(plausible, total, rank, "Plausible patch:", patch)
                elif correctness == 'wrong':
                    print(plausible, total, rank, "Wrong patch:", patch)
                elif correctness == 'timeout':
                    print(plausible, total, rank, "Timeout patch:", patch)
            else:
                print(plausible, total, rank, 'Uncompilable patch:', patch)
            validated_result['data'][proj]['output'].append({
                'patch': patch, 'correctness': correctness
            })
            shutil.copyfile(tmp_dir + "/java_programs_bak/" + proj + '.java',
                            tmp_dir + "/java_programs/" + proj + '.java')
        json.dump(validated_result, open(output_file, 'w'), indent=2)


if __name__ == '__main__':
    input_file = sys.argv[1]    # output.json containing the generated patches
    output_file = sys.argv[2]   # validation.json containing the validated result
    tmp_dir = sys.argv[3]       # directory of QuixBugs benchmark, default ../../tmp_benchmarks/QuixBugs/
    
    validate_quixbugs(input_file, output_file, tmp_dir)
