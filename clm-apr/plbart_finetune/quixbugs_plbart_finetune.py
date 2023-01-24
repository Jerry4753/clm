import codecs
import json
import sys
import os
import re
import subprocess
from transformers import PLBartForConditionalGeneration, PLBartTokenizer

PLBART_FINETUNE_DIR = os.path.abspath(__file__)[: os.path.abspath(__file__).rindex('/') + 1]
JAVA_DIR = PLBART_FINETUNE_DIR + '../../jasper/'

def command(cmd):
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = process.communicate()
    if output != b'' or err != b'':
        print(output)
        print(err)
    return output, err

def get_plbart_finetune_input(buggy_file, rem_start, rem_end, tmp_file):
    os.chdir(JAVA_DIR)
    command([
        'java', '-cp', '.:target:lib/*', 'clm.finetuning.FineTuningData', 'inference',
        buggy_file, str(rem_start), str(rem_end), tmp_file
    ])


def quixbugs_plbart_finetune_input(output_file):
    loc_fp = codecs.open(PLBART_FINETUNE_DIR + '../quixbugs/quixbugs_loc.txt', 'r', 'utf-8')
    plbart_input = {'config': 'finetune', 'data': {}}
    for line in loc_fp.readlines():
        filename, rem_loc, add_loc = line.strip().split()
        start, end = rem_loc.split('-')
        end = str(int(end) - 1) if end != start else end
        tmp_file = PLBART_FINETUNE_DIR + '../quixbugs/tmp.json'
        get_plbart_finetune_input(PLBART_FINETUNE_DIR + '../quixbugs/java_programs/' + filename + '.java', start, end, tmp_file)
        
        if not os.path.exists(tmp_file):
            print(filename, 'failed.', tmp_file, 'not found.')
        print(filename, 'succeeded')

        result = json.load(open(tmp_file, 'r'))
        buggy_function_before = re.sub('\\s+', ' ', result['buggy function before']).strip()
        buggy_line = re.sub('\\s+', ' ', result['buggy line']).strip()
        buggy_function_after = re.sub('\\s+', ' ', result['buggy function after']).strip()
        inputs = '<s> ' + buggy_function_before + ' </s> ' + buggy_line + ' </s> ' + buggy_function_after + ' </s> java'

        plbart_input['data'][filename] = {
            'loc': rem_loc,
            'input': inputs,
        }
        command(['rm', '-rf', tmp_file])
    json.dump(plbart_input, open(output_file, 'w'), indent=2)


def quixbugs_plbart_finetune_output(input_file, output_file, model_dir, model_name, num_output=10):
    tokenizer = PLBartTokenizer.from_pretrained(model_dir + model_name[:-9], src_lang="java", tgt_lang="java")
    model = PLBartForConditionalGeneration.from_pretrained(model_dir + model_name).to(device_id)
    
    plbart_output = json.load(open(input_file, 'r'))
    plbart_output['model'] = model_name
    for filename in plbart_output['data']:
        text = plbart_output['data'][filename]['input']

        print('generating', filename)

        input_ids = tokenizer(text, add_special_tokens=False, return_tensors="pt").input_ids.to(device_id)
        generated_ids = model.generate(
            input_ids, max_length=128, num_beams=num_output, num_return_sequences=num_output, 
            early_stopping=True, decoder_start_token_id=tokenizer.lang_code_to_id["java"]
        )
        output = []
        for generated_id in generated_ids:
            output.append(tokenizer.decode(generated_id, skip_special_tokens=True))
        plbart_output['data'][filename]['output'] = output
        json.dump(plbart_output, open(output_file, 'w'), indent=2)


def plbart_output_to_patch(output):
    return output.strip()


if __name__ == '__main__':
    device_id = 0   # need one GPU with 12GB memory
    model_dir = sys.argv[1]
    
    input_file = PLBART_FINETUNE_DIR + '../quixbugs/plbart_finetune_result/plbart_input.json'
    print("==========Preparing input of QuixBugs benchmark to finetuned PLBART model==========")
    quixbugs_plbart_finetune_input(input_file)
    print("==========Input written to " + input_file)
    
    for model_name in ('plbart-base-finetune', 'plbart-large-finetune'):
        output_file = PLBART_FINETUNE_DIR + '../quixbugs/plbart_finetune_result/' + '_'.join(model_name.split('-')[:-1]) + '_output.json'
        # model_dir = PLBART_FINETUNE_DIR + '../../models/'
        print("==========Generating output of Defects4J benchmark by " + model_name + "==========")
        quixbugs_plbart_finetune_output(input_file, output_file, model_dir, model_name, num_output=10)
        print("==========Output written to " + output_file)
