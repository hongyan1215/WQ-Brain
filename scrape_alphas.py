from main import WQSession
import time
import logging
import pandas as pd
from concurrent.futures import as_completed, ThreadPoolExecutor

logging.basicConfig(encoding='utf-8', level=logging.INFO, format='%(asctime)s: %(message)s')

team_params = {
    'status':               'ACTIVE',
    'members.self.status':  'ACCEPTED',
    'order':                '-dateCreated'
}

OFFSET, LIMIT = 0, 1000
def get_link(x):
    return f'https://api.worldquantbrain.com/users/self/alphas?limit={LIMIT}&offset={x}&stage=IS%1fOS&is.sharpe%3E=1.25&is.turnover%3E=0.01&is.fitness%3E=1&status=UNSUBMITTED&dateCreated%3E=2023-05-16T00:00:00-04:00&order=-dateCreated&hidden=false'

wq = WQSession()
r = wq.get('https://api.worldquantbrain.com/users/self/teams', params=team_params).json()
team_id = r['results'][0]['id']

def scrape(result):
    alpha = result['regular']['code']
    settings = result['settings']
    aid = result['id']
    passed = sum(check['result'] == 'PASS' for check in result['is']['checks'])
    failed = sum(check['result'] in ['FAIL', 'ERROR'] for check in result['is']['checks'])
    if failed != 0:
        logging.info(f'Skipping alpha due to failure')
        return -1

    # score check
    while True:
        compare_r = wq.get(f'https://api.worldquantbrain.com/teams/{team_id}/alphas/{aid}/before-and-after-performance')
        if compare_r.content: break
        time.sleep(2.5)
    score = compare_r.json()['score']
    if score['after'] <= score['before']:
        return -1

    # correlation check, prone to throttling
    while True:
        corr_r = wq.get(f'https://api.worldquantbrain.com/alphas/{aid}/correlations/self')
        if corr_r.content:
            try:
                max_corr = max(record[5] for record in corr_r.json()['records'])
                if max_corr > 0.7:
                    logging.info(f'Skipping alpha due to high correlation')
                    return -1
                score['max_corr'] = max_corr
                break
            except:
                logging.info('Correlation check throttled')
                time.sleep(5)
        else:
            time.sleep(2.5)

    # merge everything else
    score |= settings
    score['passed'], score['alpha'], score['link'] = passed, alpha, f'https://platform.worldquantbrain.com/alpha/{aid}'
    logging.info(score)
    return score

ret = []
with ThreadPoolExecutor(max_workers=6) as executor:
    try:
        while True:
            r = wq.get(get_link(OFFSET)).json()
            for f in as_completed([executor.submit(scrape, result) for result in r['results']]):
                res = f.result()
                if res != -1: ret.append(res)
            OFFSET += LIMIT
            if not r['next']: break
            r = wq.get(get_link(OFFSET)).json()
    except Exception as e:
        print(f'{type(e).__name__}: {e}')
pd.DataFrame(ret).sort_values(by='after', ascending=False).to_csv(f'alpha_scrape_result_{int(time.time())}.csv', index=False)
