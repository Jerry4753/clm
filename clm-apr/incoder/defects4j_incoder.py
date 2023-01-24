import os
import sys
import json
import codecs
import subprocess
from incoder_config import InCoderInputConfig
from transformers import AutoTokenizer, AutoModelForCausalLM

INCODER_DIR = os.path.abspath(__file__)[: os.path.abspath(__file__).rindex('/') + 1]
JAVA_DIR = INCODER_DIR + '../../jasper/'


def command(cmd):
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, err = process.communicate()
    if output != b'' or err != b'':
        print(output)
        print(err)
    return output, err


def get_incoder_input(filename, start, end, config, tmp_file):
    os.chdir(JAVA_DIR)
    command([
        'java', '-cp', '.:target:lib/*', 'clm.incoder.InCoderInputParser',
        filename, start, end, config, tmp_file
    ])


def defects4j_incoder_input(config, output_file, tmp_dir):
    loc_fp = codecs.open(INCODER_DIR + '../defects4j/defects4j_loc.txt', 'r', 'utf-8')
    incoder_input = {'config': config, 'data': {}}
    for line in loc_fp.readlines():
        proj, bug_id, path, rem_loc, add_loc = line.strip().split()
        start, end = rem_loc.split('-')
        end = str(int(end) - 1) if end != start else end
        tmp_file = INCODER_DIR + '../defects4j/tmp.json'

        subprocess.run(['defects4j', 'checkout', '-p', proj, '-v', bug_id + 'b', '-w', tmp_dir], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        get_incoder_input(tmp_dir + path, start, end, config, tmp_file)
        
        if not os.path.exists(tmp_file):
            print(proj, bug_id, 'failed.', tmp_file, 'not found.')
            continue
        print(proj, bug_id, 'succeeded')

        result = json.load(open(tmp_file, 'r'))
        if result['input'].strip() == '':
            print(proj, bug_id, 'failed. all empty.')
            continue
        result = json.load(open(tmp_file, 'r'))
        incoder_input['data'][proj + '_' + bug_id + '_' + path + '_' + rem_loc] = {
            'loc': rem_loc,
            'input': result['input'],
            'function range': result['function range']
        }

        command(['rm', '-rf', tmp_file])
        command(['rm', '-rf', tmp_dir])
        json.dump(incoder_input, open(output_file, 'w'), indent=2)


def defects4j_incoder_output(input_file, output_file, model_dir, model_name, num_output=10):
    tokenizer = AutoTokenizer.from_pretrained(model_dir + model_name)
    model = AutoModelForCausalLM.from_pretrained(model_dir + model_name)
    model.parallelize(device_map)
    
    incoder_output = json.load(open(input_file, 'r'))
    incoder_output['model'] = model_name
    for filename in incoder_output['data']:
        
        text = incoder_output['data'][filename]['input']

        input_ids = tokenizer(text, return_tensors="pt").input_ids
        if input_ids.size(1) >= 768:
            print('too long:', input_ids.size(1))
            continue
        mask_id = tokenizer('<|mask:0|>', return_tensors="pt").input_ids.squeeze(0)[1:]
        index_of_mask = (input_ids[0] == mask_id).nonzero().squeeze(-1)
        function_after_len = (index_of_mask[1] - index_of_mask[0]).item()

        print('generating', filename, input_ids.size(1), function_after_len)

        input_ids = input_ids.to(device_ids[0])
        eos_id = tokenizer.convert_tokens_to_ids('</code>')
        try:
            generated_ids = model.generate(
                input_ids, max_new_tokens=128 + function_after_len, num_beams=num_output, num_return_sequences=num_output, early_stopping=True,
                pad_token_id=eos_id, eos_token_id=eos_id
            )
        except Exception as e:
            incoder_output['data'][filename]['output'] = []
            print(str(e).split('\n')[-2:])
            continue
        output = []
        for generated_id in generated_ids:
            output.append(tokenizer.decode(generated_id, skip_special_tokens=False, clean_up_tokenization_spaces=False))
        incoder_output['data'][filename]['output'] = output
        json.dump(incoder_output, open(output_file, 'w'), indent=2)


if __name__ == '__main__':
    model_dir = sys.argv[1]
    for i, config in enumerate(InCoderInputConfig):
        input_file = INCODER_DIR + '../defects4j/incoder_result/incoder_input_c' + str(i + 1) + '.json'
        print("==========Preparing input of Defects4J benchmark to INCODER model, Config: " + config + "==========")
        defects4j_incoder_input(config, input_file, tmp_dir='/tmp/incoder/')
        print("==========Input written to " + input_file)
        
        for model_name in ('incoder-1B', 'incoder-6B'):
            if model_name == 'incoder-1B':
                device_map = {
                    0: [_ for _ in range(0, 5)],
                    1: [_ for _ in range(5, 12)],
                    2: [_ for _ in range(12, 19)],
                    3: [_ for _ in range(19, 24)]
                }
                device_ids = list(device_map.keys())    # need 4 GPUs with 4*12 GB memory in total to run incoder-1B
            else:
                device_map = {
                    0: [_ for _ in range(0, 4)], 
                    1: [_ for _ in range(4, 8)],
                    2: [_ for _ in range(8, 12)],
                    3: [_ for _ in range(12, 16)],
                    4: [_ for _ in range(16, 20)],
                    5: [_ for _ in range(20, 24)],
                    6: [_ for _ in range(24, 28)],
                    7: [_ for _ in range(28, 32)]
                }
                device_ids = list(device_map.keys())    # need 8 GPUs with 8*12 GB memory in total to run incoder-6B 
                                                        # (the author use 4 A5000 GPUs with 4*24 GB memory to run)
            
            output_file = INCODER_DIR + '../defects4j/incoder_result/' + '_'.join(model_name.split('-')) + '_output_c' + str(i + 1) + '.json'
            # model_dir = INCODER_DIR + '../models/'
            print("==========Generating output of Defects4J benchmark by " + model_name + ", Config: " + config + "==========")
            defects4j_incoder_output(input_file, output_file, model_dir, model_name)
            print("==========Output written to " + output_file)
